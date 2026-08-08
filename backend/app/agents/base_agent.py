"""BaseAgent: the failure-isolation envelope (now actually used).

execute() is the ONLY way the orchestrator invokes an agent. It guarantees:
timing, status envelope, event emission, version stamping (rule 2), and that
one agent's failure can never abort a run.
"""
import time
from abc import ABC, abstractmethod

from app.core.events import Event, bus
from app.core.logging import get_logger
from app.core.versions import AGENT_VERSIONS

log = get_logger("agent")


class BaseAgent(ABC):
    key: str = "agent"          # stable id used in versions + payload keys
    name: str = "Agent"

    async def execute(self, ctx, **kwargs) -> dict:
        start = time.perf_counter()
        await bus.publish(Event("agent.started", ctx.run_id, {"agent": self.key}))
        try:
            data = await self.run(ctx, **kwargs)
            elapsed = round(time.perf_counter() - start, 2)
            await bus.publish(Event("agent.completed", ctx.run_id,
                                    {"agent": self.key, "seconds": elapsed}))
            return {
                "agent": self.name,
                "agent_key": self.key,
                "agent_version": AGENT_VERSIONS.get(self.key, "0"),
                "status": "completed",
                "execution_time": elapsed,
                "data": data,
            }
        except Exception as exc:
            elapsed = round(time.perf_counter() - start, 2)
            log.warning("run_id=%s agent=%s failed after %.2fs: %s",
                        ctx.run_id, self.key, elapsed, exc)
            await bus.publish(Event("agent.failed", ctx.run_id,
                                    {"agent": self.key, "seconds": elapsed, "error": str(exc)}))
            return {
                "agent": self.name,
                "agent_key": self.key,
                "agent_version": AGENT_VERSIONS.get(self.key, "0"),
                "status": "failed",
                "execution_time": elapsed,
                "error": str(exc),
                "data": None,
            }

    @abstractmethod
    async def run(self, ctx, **kwargs):
        ...
