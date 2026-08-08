"""Connector layer — the platform's window onto the live public web.

Each connector collects real, public data from one free source and returns
normalized items. Connectors never fabricate: if a source is unreachable or
returns nothing, the connector reports that honestly (available=False or an
empty list) so the UI can show "Not yet available from public sources".

Connectors are deliberately uniform so the research pipeline can fan out across
many sources in parallel and fold every result into the same Evidence → Claim →
graph pipeline that powers the whole platform. This is what makes the product
one Intelligence OS rather than three separate tools.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.core.throttle import search_cache, stable_key

log = get_logger("connectors")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ConnectorItem:
    """One normalized piece of collected intelligence."""
    kind: str                     # e.g. "release", "dns_record", "security_header"
    title: str
    detail: str = ""
    url: str | None = None
    at: str | None = None         # ISO timestamp of the underlying event, if known
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorResult:
    connector: str
    available: bool               # was the source reachable + usable?
    items: list[ConnectorItem] = field(default_factory=list)
    note: str = ""                # honest explanation when unavailable/empty
    collected_at: str = field(default_factory=_now_iso)

    def as_dict(self) -> dict:
        return {
            "connector": self.connector,
            "available": self.available,
            "note": self.note,
            "collected_at": self.collected_at,
            "items": [i.__dict__ for i in self.items],
        }


class Connector:
    """Base connector. Subclasses implement `collect`. Results are cached
    (shared TTL cache) so repeated collection across specialists is deduped —
    the same performance discipline as the LLM/search layer."""
    name: str = "connector"
    cache_ttl: float = 1800.0

    async def collect(self, target: str, **kwargs) -> ConnectorResult:  # noqa: D401
        raise NotImplementedError

    async def collect_cached(self, target: str, **kwargs) -> ConnectorResult:
        key = stable_key("connector", self.name, target, sorted(kwargs.items()))
        cached = await search_cache.get(key)
        if cached is not None:
            return cached
        try:
            result = await self.collect(target, **kwargs)
        except Exception as exc:  # noqa: BLE001 - honest failure, never fake
            log.warning("connector %s failed for %s: %s", self.name, target, exc)
            result = ConnectorResult(
                connector=self.name, available=False,
                note=f"{self.name} unavailable: {type(exc).__name__}")
        await search_cache.set(key, result, self.cache_ttl)
        return result


async def collect_all(connectors: list[Connector], target: str,
                      **kwargs) -> dict[str, ConnectorResult]:
    """Fan out across connectors concurrently (safe parallelism) and gather
    every result. One slow/unavailable source never blocks the others."""
    results = await asyncio.gather(
        *[c.collect_cached(target, **kwargs) for c in connectors],
        return_exceptions=True,
    )
    out: dict[str, ConnectorResult] = {}
    for connector, res in zip(connectors, results):
        if isinstance(res, Exception):
            out[connector.name] = ConnectorResult(
                connector=connector.name, available=False,
                note=f"error: {type(res).__name__}")
        else:
            out[connector.name] = res
    return out
