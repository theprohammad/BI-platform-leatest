"""Event bus abstraction (Blueprint §1.7).

Phase 0: in-process pub/sub + per-run event log (outbox-shaped, so the swap
to Redis Streams/worker fan-out later changes the transport, not the callers).
All progress, agent lifecycle and (later) graph mutations flow through here —
SSE in Phase 1 simply subscribes.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

Handler = Callable[["Event"], Awaitable[None]]


@dataclass
class Event:
    type: str                 # e.g. "agent.started", "agent.completed", "llm.call"
    run_id: str
    payload: dict = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict:
        return {"type": self.type, "run_id": self.run_id, "payload": self.payload, "at": self.at}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Handler] = []
        self._log: dict[str, list[Event]] = {}

    def subscribe(self, handler: Handler) -> None:
        self._subscribers.append(handler)

    async def publish(self, event: Event) -> None:
        self._log.setdefault(event.run_id, []).append(event)
        for handler in list(self._subscribers):
            try:
                await handler(event)
            except Exception:  # a bad subscriber must never break a run
                pass

    def run_events(self, run_id: str) -> list[dict]:
        return [e.as_dict() for e in self._log.get(run_id, [])]

    def clear_run(self, run_id: str) -> None:
        self._log.pop(run_id, None)


bus = EventBus()


def publish_nowait(event: Event) -> None:
    """Fire-and-forget publish from sync contexts."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(bus.publish(event))
    except RuntimeError:
        asyncio.run(bus.publish(event))
