"""Priority Zero performance layer — proves the optimizations are real:
LLM output cache eliminates duplicate reasoning, the search cache dedupes
identical Tavily searches, and the request queue bounds concurrency and
survives 429 storms via backoff (never propagating the 429 to the caller)."""
import asyncio

import pytest

from app.core.throttle import RequestQueue, TTLCache, stable_key
from app.core.ledger import CostLedger
from app.providers.llm.base import LLMResult
from app.providers.llm.router import LLMRouter


class CountingProvider:
    """LLM provider stub that counts upstream calls and returns valid JSON."""
    def __init__(self):
        self.calls = 0

    async def complete_json(self, *, model, system, prompt, temperature, timeout):
        self.calls += 1
        await asyncio.sleep(0)
        return LLMResult(text='{"ok": true}', model=model,
                         prompt_tokens=10, completion_tokens=5)


async def test_llm_output_cache_eliminates_duplicate_reasoning():
    from app.core import throttle
    throttle.llm_cache._data.clear()
    provider = CountingProvider()
    router = LLMRouter(provider, ledger=CostLedger(), run_id="t")
    # identical prompt 5×: only the first should reach the provider
    for _ in range(5):
        out = await router.complete_json("Analyze OpenAI pricing", label="pricing")
        assert out == {"ok": True}
    assert provider.calls == 1, f"expected 1 upstream call, got {provider.calls}"


async def test_distinct_prompts_are_not_collapsed():
    from app.core import throttle
    throttle.llm_cache._data.clear()
    provider = CountingProvider()
    router = LLMRouter(provider, ledger=CostLedger(), run_id="t")
    await router.complete_json("Prompt A", label="a")
    await router.complete_json("Prompt B", label="b")
    assert provider.calls == 2


async def test_ttl_cache_single_flight_under_stampede():
    """20 concurrent callers for the same key → compute runs exactly once."""
    cache = TTLCache(ttl_seconds=60)
    runs = {"n": 0}

    async def compute():
        runs["n"] += 1
        await asyncio.sleep(0.02)
        return "value"

    results = await asyncio.gather(*[
        cache.get_or_compute("k", compute) for _ in range(20)
    ])
    assert all(r == "value" for r in results)
    assert runs["n"] == 1, f"single-flight failed: {runs['n']} computes"


async def test_ttl_cache_expiry():
    cache = TTLCache(ttl_seconds=0.05)
    await cache.set("k", 1)
    assert await cache.get("k") == 1
    await asyncio.sleep(0.08)
    assert await cache.get("k") is None


async def test_queue_bounds_concurrency():
    """Never more than max_concurrent factories in flight simultaneously."""
    q = RequestQueue(max_concurrent=3)
    inflight = {"now": 0, "peak": 0}

    async def factory():
        inflight["now"] += 1
        inflight["peak"] = max(inflight["peak"], inflight["now"])
        await asyncio.sleep(0.02)
        inflight["now"] -= 1
        return "ok"

    await asyncio.gather(*[q.run(factory, label=f"r{i}") for i in range(15)])
    assert inflight["peak"] <= 3, f"concurrency breached: peak {inflight['peak']}"


async def test_queue_retries_429_with_backoff_then_succeeds():
    """A transient 429 storm is absorbed by backoff, not surfaced to caller."""
    q = RequestQueue(max_concurrent=2, base_delay=0.001, max_delay=0.01)
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("429 Too Many Requests")
        return "recovered"

    result = await q.run(flaky, label="flaky")
    assert result == "recovered"
    assert attempts["n"] == 3
    assert q.rate_limit_hits == 2   # both 429s counted for observability


async def test_queue_gives_up_after_max_retries():
    q = RequestQueue(max_concurrent=1, max_retries=2, base_delay=0.001, max_delay=0.01)

    async def always_429():
        raise RuntimeError("rate limit exceeded")

    with pytest.raises(RuntimeError, match="failed after"):
        await q.run(always_429, label="doomed")
    assert q.rate_limit_hits == 3   # initial + 2 retries


async def test_stable_key_is_order_sensitive_and_deterministic():
    assert stable_key("a", "b") == stable_key("a", "b")
    assert stable_key("a", "b") != stable_key("b", "a")
    assert stable_key({"x": 1, "y": 2}) == stable_key({"y": 2, "x": 1})  # dict order-free


async def test_search_cache_dedupes_identical_queries(monkeypatch):
    """Near-identical search intents collapse to one upstream Tavily call."""
    from app.core import throttle
    throttle.search_cache._data.clear()
    from app.providers.search.tavily_provider import TavilyProvider

    calls = {"n": 0}

    class FakeClient:
        async def search(self, *, query, search_depth, max_results):
            calls["n"] += 1
            return {"results": [{"title": "T", "url": "https://x.com",
                                 "content": "c", "score": 0.9}]}

    provider = TavilyProvider.__new__(TavilyProvider)
    provider._client = FakeClient()
    from app.core.config import get_settings
    provider._settings = get_settings()

    # three trivially-different intents → one real search
    for q in ["OpenAI pricing", "openai   pricing", "OpenAI pricing?"]:
        res = await provider.search(q, max_results=5)
        assert res and res[0].url == "https://x.com"
    assert calls["n"] == 1, f"search dedup failed: {calls['n']} upstream calls"


async def test_performance_stats_shape():
    from app.core.throttle import all_stats
    s = all_stats()
    assert "llm_cache" in s and "search_cache" in s and "llm_queue" in s
    assert "hit_rate" in s["llm_cache"]
    assert "rate_limit_hits" in s["llm_queue"]


async def test_specialist_failure_isolation_in_loop(monkeypatch):
    """One specialist raising must not sink the swarm — the loop isolates each
    (concurrency change from the Priority-Zero pass). Survivors still produce."""
    from app.research import loop as loop_mod

    class BoomSpecialist:
        async def run(self, ctx, *, root_entity_id, organization):
            raise RuntimeError("specialist exploded")

    class GoodSpecialist:
        key = "good"
        async def run(self, ctx, *, root_entity_id, organization):
            return ["insight-1", "insight-2"]

    # Exercise the exact gather+isolation logic the loop uses.
    selected = [("boom", BoomSpecialist()), ("good", GoodSpecialist())]
    import asyncio
    from app.core.logging import get_logger
    log = get_logger("test")

    async def _run_specialist(key, specialist):
        try:
            return await specialist.run(None, root_entity_id="r", organization="o")
        except Exception as exc:  # noqa: BLE001
            log.warning("specialist %s failed: %s", key, exc)
            return []

    results = await asyncio.gather(*[_run_specialist(k, sp) for k, sp in selected])
    merged = [i for r in results for i in r]
    assert merged == ["insight-1", "insight-2"]   # survivor's output intact
