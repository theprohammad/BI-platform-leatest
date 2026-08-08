"""Planner v2 (P2 replan, P5 envelopes) + S6 durable jobs/events + S8 refresh."""
import asyncio
import json

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import EntityType
from app.graph.store import IntelligenceGraph
from app.providers.llm.base import LLMResult
from app.providers.llm.router import LLMRouter
from app.research.loop import ResearchLoop
from app.tools.registry import Budget, BudgetExceeded, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
import app.tools.web_tools    # noqa: F401
from tests.fakes_v2 import UNI, FakeSearchV2, ScriptedLLM


@pytest.fixture
async def graph(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    @event.listens_for(engine.sync_engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")
    import app.graph.models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield IntelligenceGraph(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def make_ctx(graph, llm=None) -> ToolContext:
    return ToolContext(workspace_id="ws", run_id="test", graph=graph,
                       search=FakeSearchV2(),
                       llm=LLMRouter(llm or ScriptedLLM(), ledger=CostLedger(),
                                     run_id="test"),
                       budget=Budget(max_searches=50, max_llm_calls=80),
                       organization_id="org1")


# ---------------- P5: budget envelopes ---------------------------------------

async def test_topic_envelopes_enforced(graph):
    ctx = make_ctx(graph)
    ctx.budget.topic_envelopes = {"pricing": 1}
    await registry.invoke(ctx, "web.search", query="q1", topic="pricing")
    with pytest.raises(BudgetExceeded):
        await registry.invoke(ctx, "web.search", query="q2", topic="pricing")
    # other topics unaffected
    await registry.invoke(ctx, "web.search", query="q3", topic="market")


async def test_envelopes_derived_from_objectives(graph):
    ctx = make_ctx(graph)
    ResearchLoop()._apply_envelopes(ctx, ["understand competitors deeply"])
    env = ctx.budget.topic_envelopes
    assert env["competitors"] >= int(50 * 0.6)          # named objective ≥60%
    assert env["pricing"] < env["competitors"]          # others get the small share


# ---------------- P2: single bounded replan ------------------------------------

class ReplanningLLM(ScriptedLLM):
    """Replan proposes exactly one follow-up; a second replan would loop forever
    if the cap were broken — the test proves it can't."""
    def __init__(self):
        super().__init__()
        self.replans = 0

    async def complete_json_route(self, prompt):
        if "reviewing first-wave findings" in prompt:
            self.replans += 1
            return {"hypotheses": [{"question": "Follow up on Beta University",
                                    "topic": "competitors",
                                    "queries": ["beta university details"]}]}
        if "competitive intelligence specialist" in prompt:
            return {"insights": []}
        return await super().complete_json_route(prompt)


async def test_replan_runs_exactly_once_and_wave2_executes(graph):
    root = await graph.resolve_entity("ws", UNI, EntityType.ORGANIZATION)
    llm = ReplanningLLM()
    ctx = make_ctx(graph, llm)
    stats = await ResearchLoop(max_hypotheses=2).run(
        ctx, brief={"organization": UNI, "objectives": []}, root_entity_id=root.id)
    assert llm.replans == 1                              # P2 hard cap
    assert stats["replan_hypotheses"] == ["Follow up on Beta University"]
    assert "beta university details" in ctx.search.queries  # wave 2 really ran


# ---------------- S6: durable jobs + SSE replay after "restart" ----------------

async def test_jobs_and_events_survive_process_state_loss(tmp_path, monkeypatch):
    from app.db import session as db
    from app.core.events import Event, bus
    from app.runner.task_runner import TaskRunner

    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/d.db", use_alembic=False)
    runner = TaskRunner()

    async def job():
        await bus.publish(Event("research.stage", "runX", {"stage": "understand"}))
        await bus.publish(Event("run.completed", "runX", {}))
        return {"claims": 3}

    runner.start(job, run_id="runX")
    for _ in range(100):
        await asyncio.sleep(0.02)
        row = await db.get_job("runX")
        if row is not None and row.status != "running":
            break
    assert row.status == "completed" and row.result == {"claims": 3}

    # simulate restart: in-memory state gone, DB remains
    runner._jobs.clear()
    bus._log.clear()
    events = await db.events_for_run("runX")
    assert [e["type"] for e in events][-1] == "run.completed"   # SSE replay source
    assert bus.run_events("runX") == []                          # leak fixed: cleared


# ---------------- S8: refresh --------------------------------------------------

async def test_refresh_refetches_and_reports(graph, monkeypatch):
    from app.research.refresh import run_refresh
    root = await graph.resolve_entity("ws", UNI, EntityType.ORGANIZATION)
    ctx = make_ctx(graph)
    # first: seed via a normal investigation
    loop = ResearchLoop(max_hypotheses=1)
    await loop.run(ctx, brief={"organization": UNI, "objectives": []},
                   root_entity_id=root.id)

    changed_page = {"url": "https://acme.edu/about", "title": "About",
                    "text": f"{UNI} was founded in 2004 in Lahore. "
                            f"NEW: {UNI} now enrolls 30,000 students. " * 5}

    async def fake_fetch(ctx_, p):
        return changed_page
    monkeypatch.setattr(registry.get("web.fetch"), "handler", fake_fetch)

    ctx2 = make_ctx(graph)
    stats = await run_refresh(ctx2, organization=UNI, root_entity_id=root.id,
                              since_iso="2000-01-01T00:00:00+00:00")
    assert stats["refetched_urls"] >= 1
    assert stats["change_report"]["new_claims"] >= 1
    assert isinstance(stats["topics_targeted"], list)
