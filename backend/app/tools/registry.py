"""THE TOOL LAYER — the real platform (owner rule 3 of the approved rules).

Every consumer — research loop, specialists, chat, the HTTP API, future
monitoring/extension/marketplace — invokes capabilities ONLY through this
registry. Business logic lives in tool handlers; consumers compose tools.

STABLE INTERFACE (rule 4): Tool names, input models and result shapes are a
public contract. Handlers may be reimplemented freely.

Every invocation is budget-checked and emitted on the event bus, so cost
control and observability are properties of the platform, not of each caller.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.core.events import Event, bus
from app.core.logging import get_logger

log = get_logger("tools")


@dataclass
class Budget:
    """Research must terminate (Blueprint Part V).
    P5: optional per-topic search envelopes derived from brief objectives;
    a 20% unallocated reserve is mandated by the spec (planner enforces)."""
    max_searches: int = 20
    max_llm_calls: int = 40
    deadline_epoch: float | None = None
    used_searches: int = 0
    used_llm_calls: int = 0
    topic_envelopes: dict = field(default_factory=dict)   # topic -> max searches
    used_by_topic: dict = field(default_factory=dict)

    def charge(self, category: str, topic: str | None = None) -> None:
        if self.deadline_epoch and time.time() > self.deadline_epoch:
            raise BudgetExceeded("wall-clock budget exhausted")
        if category == "search":
            self.used_searches += 1
            if self.used_searches > self.max_searches:
                raise BudgetExceeded("search budget exhausted")
            if topic and topic in self.topic_envelopes:
                used = self.used_by_topic.get(topic, 0) + 1
                self.used_by_topic[topic] = used
                if used > self.topic_envelopes[topic]:
                    raise BudgetExceeded(f"search envelope exhausted for topic '{topic}'")
        elif category == "llm":
            self.used_llm_calls += 1
            if self.used_llm_calls > self.max_llm_calls:
                raise BudgetExceeded("LLM call budget exhausted")


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class ToolContext:
    """Everything a tool may touch. Constructed per run/conversation."""
    workspace_id: str
    run_id: str
    graph: Any                    # IntelligenceGraph
    search: Any                   # SearchProvider
    llm: Any                      # LLMRouter
    budget: Budget = field(default_factory=Budget)
    organization_id: str | None = None
    ledger: Any = None                # CostLedger (shared with the LLM router)
    embedder: Any = None              # EmbeddingProvider (lazy via .embedding())
    resolver: Any = None              # EntityResolver (lazy, per-run adjudication cap)
    playbook: Any = None              # PlaybookSpec (Phase 3; None → default)

    def embedding(self):
        if self.embedder is None:
            from app.graph.embeddings import build_embedder
            self.embedder = build_embedder()
        return self.embedder

    def entity_resolver(self):
        if self.resolver is None:
            from app.graph.resolver import EntityResolver
            self.resolver = EntityResolver()
        return self.resolver


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], Awaitable[Any]]
    cost_category: str | None = None   # "search" | "llm" | None (graph reads are free)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def describe(self) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_model.model_json_schema()}
                for t in self._tools.values()]

    async def invoke(self, ctx: ToolContext, tool_name: str, /, **kwargs) -> Any:
        # positional-only tool_name so tool input fields (e.g. "name") never collide
        name = tool_name
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown tool: {name}")
        if tool.cost_category:
            ctx.budget.charge(tool.cost_category, topic=kwargs.get("topic"))
        params = tool.input_model.model_validate(kwargs)
        start = time.perf_counter()
        try:
            result = await tool.handler(ctx, params)
            await bus.publish(Event("tool.invoked", ctx.run_id, {
                "tool": name, "ms": round((time.perf_counter() - start) * 1000),
            }))
            return result
        except Exception as exc:
            await bus.publish(Event("tool.failed", ctx.run_id,
                                    {"tool": name, "error": str(exc)}))
            raise


registry = ToolRegistry()
