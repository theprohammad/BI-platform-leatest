"""Tiered LLM router: model selection, timeout, JSON validation + one repair
retry, cost ledger recording, event emission. The only door to any LLM.
"""
import asyncio
import json

from app.core.config import get_settings
from app.core.events import Event, bus
from app.core.ledger import CostLedger
from app.core.logging import get_logger
from app.core.throttle import llm_cache, llm_queue, stable_key
from app.providers.llm.base import LLMProvider, Tier

log = get_logger("llm.router")

DEFAULT_SYSTEM = (
    "You are a senior business intelligence analyst. "
    "Always return valid JSON only. Never use markdown."
)

_REPAIR_SUFFIX = (
    "\n\nYour previous response was not valid JSON. "
    "Return ONLY a single valid JSON object matching the requested schema."
)


class LLMRouter:
    def __init__(self, provider: LLMProvider, ledger: CostLedger | None = None,
                 run_id: str = "-") -> None:
        self._provider = provider
        self._ledger = ledger
        self._run_id = run_id
        self._settings = get_settings()

    def _model_for(self, tier: Tier) -> str:
        s = self._settings
        return {Tier.EXTRACT: s.model_extract, Tier.REASON: s.model_reason,
                Tier.JUDGE: s.model_judge}[tier]

    async def complete_json(self, prompt: str, *, tier: Tier = Tier.REASON,
                            label: str = "llm", system: str = DEFAULT_SYSTEM) -> dict:
        s = self._settings
        model = self._model_for(tier)

        # ---- Output cache (Priority Zero): identical reasoning is reused ------
        # Keyed on everything that changes the output. Deterministic-ish calls
        # (low temperature) are safe to memoize for the cache TTL; this is the
        # single biggest lever against duplicate LLM work across specialists.
        cache_key = stable_key("llm.v1", model, system, prompt, s.llm_temperature)
        cached = await llm_cache.get(cache_key)
        if cached is not None:
            await bus.publish(Event("llm.cache_hit", self._run_id,
                                    {"label": label, "model": model}))
            return cached

        attempt_prompt = prompt
        last_error: Exception | None = None

        for attempt in range(s.llm_max_retries + 1):
            try:
                # ---- Queued execution: bounds concurrent Groq calls + backoff
                result = await llm_queue.run(
                    lambda: asyncio.wait_for(
                        self._provider.complete_json(
                            model=model, system=system, prompt=attempt_prompt,
                            temperature=s.llm_temperature,
                            timeout=s.llm_timeout_seconds,
                        ),
                        timeout=s.llm_timeout_seconds + 5,
                    ),
                    label=label,
                )
            except Exception as exc:  # provider/network/timeout (post-retry)
                last_error = exc
                log.warning("call=%s model=%s attempt=%d error=%s", label, model, attempt, exc)
                continue

            if self._ledger is not None:
                self._ledger.add(label, result.model, result.prompt_tokens, result.completion_tokens)
            await bus.publish(Event("llm.call", self._run_id, {
                "label": label, "model": result.model, "tier": tier.value,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens, "attempt": attempt,
            }))

            try:
                parsed = json.loads(result.text)
            except json.JSONDecodeError as exc:
                last_error = exc
                log.warning("call=%s model=%s attempt=%d invalid_json", label, model, attempt)
                attempt_prompt = prompt + _REPAIR_SUFFIX  # one repair pass
                continue

            await llm_cache.set(cache_key, parsed)   # cache only clean parses
            return parsed

        raise RuntimeError(f"LLM call '{label}' failed after retries: {last_error}")


def build_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "groq":
        from app.providers.llm.groq_provider import GroqProvider
        return GroqProvider(api_key=s.groq_api_key)
    raise ValueError(f"Unknown llm_provider: {s.llm_provider}")
