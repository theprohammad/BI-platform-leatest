"""Performance substrate (Priority Zero): an in-process TTL cache and a
concurrency-limited async execution queue with 429-aware exponential backoff.

This is an internal optimization layer (allowed extension) — it changes no
public API and no provider interface. The LLM router and search provider call
into it to (a) reuse identical work instead of repeating it, and (b) cap
in-flight provider requests so we stop flooding the NVIDIA endpoint during 429 storms.

Design notes
------------
* Cache is keyed by a stable content hash. Values are cloned on read via the
  caller (dicts/lists), so cache entries are never mutated by consumers.
* The queue is a global semaphore per provider-class, not per-router-instance,
  because every research run builds its own LLMRouter but they all share the
  same upstream NVIDIA account and the same rate limit.
* Backoff is exponential with full jitter, and specifically lengthened when the
  provider signals 429 / rate limit, which is the exact failure the spec calls
  out. We never "solve 429 by adding fixed delays" — throttling is adaptive and
  only engages under contention or explicit rate-limit signals.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

from app.core.logging import get_logger

log = get_logger("throttle")

T = TypeVar("T")


def stable_key(*parts: Any) -> str:
    """Deterministic hash of arbitrary JSON-able parts (order-sensitive)."""
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    value: Any
    expires_at: float


@dataclass
class TTLCache:
    """Async-safe TTL cache with hit/miss stats and a hard size cap (LRU-ish:
    oldest-expiry evicted first when full)."""
    ttl_seconds: float = 900.0
    max_entries: int = 4096
    _data: dict[str, _Entry] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    hits: int = 0
    misses: int = 0

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            if entry.expires_at < time.monotonic():
                del self._data[key]
                self.misses += 1
                return None
            self.hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        async with self._lock:
            if len(self._data) >= self.max_entries:
                # evict the entry closest to expiry
                oldest = min(self._data.items(), key=lambda kv: kv[1].expires_at)
                del self._data[oldest[0]]
            self._data[key] = _Entry(
                value=value,
                expires_at=time.monotonic() + (ttl if ttl is not None else self.ttl_seconds),
            )

    async def get_or_compute(
        self, key: str, compute: Callable[[], Awaitable[T]], ttl: float | None = None
    ) -> T:
        """Single-flight: concurrent callers for the same key await one compute."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        async with self._inflight_lock(key):
            cached = await self.get(key)         # re-check after acquiring
            if cached is not None:
                return cached
            value = await compute()
            await self.set(key, value, ttl)
            return value

    # per-key in-flight locks so identical work runs once even under a stampede
    _inflight: dict[str, asyncio.Lock] = field(default_factory=dict)
    _inflight_guard: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _inflight_lock(self, key: str) -> asyncio.Lock:
        # cheap sync accessor; creation guarded below
        lock = self._inflight.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._inflight[key] = lock
        return lock

    def stats(self) -> dict[str, int | float]:
        total = self.hits + self.misses
        return {
            "hits": self.hits, "misses": self.misses, "entries": len(self._data),
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()
            self.hits = self.misses = 0


class RequestQueue:
    """Concurrency-limited executor with 429-aware exponential backoff + jitter.

    `run()` wraps any coroutine factory. It bounds global in-flight calls to
    `max_concurrent`, and on failure retries with backoff — longer when the
    error looks like a rate limit. This is what prevents 429 storms: instead of
    N specialists firing M calls simultaneously, calls queue behind a semaphore
    and retry politely.
    """

    def __init__(self, max_concurrent: int = 4, max_retries: int = 4,
                 base_delay: float = 0.5, max_delay: float = 20.0) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.rate_limit_hits = 0
        self.retries = 0

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        text = f"{type(exc).__name__} {exc}".lower()
        return "429" in text or "rate limit" in text or "rate_limit" in text \
            or "too many requests" in text

    async def run(self, factory: Callable[[], Awaitable[T]], *,
                  label: str = "req") -> T:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            async with self._sem:
                try:
                    return await factory()
                except Exception as exc:  # noqa: BLE001 - provider errors vary
                    last = exc
                    rate_limited = self._is_rate_limit(exc)
                    if rate_limited:
                        self.rate_limit_hits += 1
                    if attempt >= self.max_retries:
                        break
                    self.retries += 1
                    # exponential backoff with full jitter; rate limits back off harder
                    ceiling = min(self.max_delay,
                                  self.base_delay * (2 ** attempt) * (3 if rate_limited else 1))
                    delay = random.uniform(0, ceiling)
                    log.warning("queue label=%s attempt=%d rate_limited=%s backoff=%.2fs err=%s",
                                label, attempt, rate_limited, delay, exc)
            await asyncio.sleep(delay)   # sleep OUTSIDE the semaphore (frees a slot)
        raise RuntimeError(f"request '{label}' failed after {self.max_retries} retries: {last}")

    def stats(self) -> dict[str, int]:
        return {"max_concurrent": self.max_concurrent,
                "rate_limit_hits": self.rate_limit_hits, "retries": self.retries}


# ---- Process-global singletons (shared across all runs / routers) -----------
# One LLM queue and cache per process because they front a single upstream
# account with a single rate limit.
llm_cache = TTLCache(ttl_seconds=1800.0)       # 30 min: reasoning is stable
search_cache = TTLCache(ttl_seconds=3600.0)    # 60 min: web results change slowly
llm_queue = RequestQueue(max_concurrent=4)     # cap concurrent NVIDIA calls


def configure_llm_queue(max_concurrent: int) -> None:
    """Allow settings to size the queue at startup without changing call sites."""
    global llm_queue
    llm_queue = RequestQueue(max_concurrent=max_concurrent)


def all_stats() -> dict[str, Any]:
    return {
        "llm_cache": llm_cache.stats(),
        "search_cache": search_cache.stats(),
        "llm_queue": llm_queue.stats(),
    }
