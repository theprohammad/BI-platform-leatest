"""Phase 3 regression matrix: Critic (adjudication guardrails, insight review),
specialist swarm, playbooks, recommendations, reconciliation sweep, insight
staleness, jobs reaper, event retention, value_entity_id semantics."""
import asyncio
import json

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.critic import Critic
from app.agents.recommender import Recommender
from app.agents.specialists import SPECIALISTS
from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import EntityType, TrustVector
from app.graph.store import IntelligenceGraph
from app.playbooks.registry import get_playbook
from app.providers.llm.base import LLMResult
from app.providers.llm.router import LLMRouter
from app.tools.registry import Budget, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
import app.tools.web_tools    # noqa: F401
from tests.fakes_v2 import FakeSearchV2, ScriptedLLM


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


def make_ctx(graph, llm=None, playbook=None) -> ToolContext:
    return ToolContext(workspace_id="ws", run_id="t", graph=graph,
                       search=FakeSearchV2(),
                       llm=LLMRouter(llm or ScriptedLLM(), ledger=CostLedger(),
                                     run_id="t"),
                       budget=Budget(max_searches=99, max_llm_calls=99),
                       organization_id="org1", playbook=playbook)


async def ev(ctx, url, content):
    return (await registry.invoke(ctx, "graph.ingest_evidence", url=url,
                                  title="t", content=content))["evidence_id"]


async def make_dispute(graph, ctx, root):
    """strong .edu claim vs newer weak blogspot claim → open dispute."""
    e_edu = await ev(ctx, "https://acme.edu/r", "official ranking twelve content")
    e_blog = await ev(ctx, "https://blogspot.com/r", "blog says ranking thirty")
    strong = await registry.invoke(ctx, "graph.write_claim",
                                   subject_entity_id=root.id,
                                   statement="Ranked 12th.", predicate="ranking",
                                   value="12", as_of="2026-01-01", topic="market",
                                   evidence_ids=[e_edu])
    weak = await registry.invoke(ctx, "graph.write_claim",
                                 subject_entity_id=root.id,
                                 statement="Ranked 30th.", predicate="ranking",
                                 value="30", as_of="2026-06-01", topic="market",
                                 evidence_ids=[e_blog])
    disputes = [i for i in await graph.insights("ws", "org1")
                if i.kind.value == "dispute"
                and i.debate_status not in ("resolved", "deferred")
                and {strong, weak} <= set(i.claim_ids)]
    assert len(disputes) == 1
    return strong, weak, disputes[0], e_edu, e_blog


class VerdictLLM(ScriptedLLM):
    """Adjudicator returning a scripted verdict; everything else default."""
    def __init__(self, verdict_factory):
        super().__init__()
        self._factory = verdict_factory

    async def complete_json_route(self, prompt):
        if "dispute adjudicator" in prompt:
            return self._factory(prompt)
        return await super().complete_json_route(prompt)


# ================= Critic: adjudication =======================================

async def test_adjudication_upholds_winner_with_lineage(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    strong, weak, dispute, e_edu, _ = await make_dispute(graph, ctx, root)

    def verdict(prompt):
        return {"winner": strong, "rationale": "official source outweighs blog",
                "citations": [e_edu]}
    ctx2 = make_ctx(graph, VerdictLLM(verdict))
    stats = await Critic().adjudicate_disputes(ctx2)
    assert stats == {"adjudicated": 1, "deferred": 0, "resolved": 1}
    weak_row = (await graph.get_claims([weak]))[0]
    assert weak_row.status == "superseded" and weak_row.superseded_by == strong
    trans = await graph.transitions_for(weak)
    assert trans[-1]["reason"] == "adjudicated"          # verdict in the lineage
    disputes = [i for i in await graph.insights("ws", "org1")
                if i.kind.value == "dispute"]
    assert all(d.debate_status == "resolved" for d in disputes)  # auto-resolved
    # rationale is still recorded (audit trail) but is separable from the
    # narrative body so it is never shown inline to users.
    from app.graph.store import split_validation_note
    public_body, note = split_validation_note(disputes[0].body)
    assert "official source outweighs blog" in note
    assert "[critic]" not in public_body and "[[validation]]" not in public_body


async def test_adjudication_guardrails_defer(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    strong, weak, dispute, e_edu, e_blog = await make_dispute(graph, ctx, root)

    # (a) fabricated citations → defer
    ctx_a = make_ctx(graph, VerdictLLM(lambda p: {
        "winner": strong, "rationale": "x", "citations": ["ev_fabricated"]}))
    stats = await Critic().adjudicate_disputes(ctx_a)
    assert stats["deferred"] == 1 and stats["resolved"] == 0
    assert (await graph.get_claims([weak]))[0].status == "active"
    deferred = [i for i in await graph.insights("ws", "org1")
                if i.kind.value == "dispute"][0]
    assert deferred.debate_status == "deferred"

    # deferred disputes are skipped on the next pass
    calls = {"n": 0}
    def count(prompt):
        calls["n"] += 1
        return {"winner": None, "rationale": "", "citations": []}
    await Critic().adjudicate_disputes(make_ctx(graph, VerdictLLM(count)))
    assert calls["n"] == 0

    # (b) trust-gap overrule without exclusive evidence → defer (fresh dispute)
    root2 = await graph.resolve_entity("ws", "Beta", EntityType.ORGANIZATION)
    strong2, weak2, *_ = await make_dispute(graph, ctx, root2)
    ctx_b = make_ctx(graph, VerdictLLM(lambda p: {
        "winner": weak2, "rationale": "blog is right",
        "citations": [e_edu]}))       # cites the STRONG side's evidence only
    stats = await Critic().adjudicate_disputes(ctx_b)
    assert stats["deferred"] == 1
    assert (await graph.get_claims([strong2]))[0].status == "active"


# ================= Critic: insight review + staleness =========================

async def test_insight_review_and_staleness(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.edu/1", "review test evidence content")
    claim = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                  statement="Enrollment is 25,000.",
                                  predicate="enrollment", value="25000",
                                  as_of="2025-01-01",
                                  topic="profile", evidence_ids=[e1])
    insight = await registry.invoke(ctx, "graph.write_insight", kind="finding",
                                    title="Growth", body="Enrollment is large.",
                                    claim_ids=[claim], authored_by="test",
                                    trust=TrustVector(confidence=0.5))
    stats = await Critic().review_insights(ctx, [insight])
    assert stats == {"reviewed": 1, "validated": 1, "rejected": 0}
    rows = [i for i in await graph.insights("ws", "org1") if i.id == insight]
    assert rows[0].debate_status == "validated"

    # premise dies → insight flagged stale automatically
    e2 = await ev(ctx, "https://b.gov/2", "newer enrollment evidence content")
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                          statement="Enrollment is 30,000.", predicate="enrollment",
                          value="30000", as_of="2026-06-01", topic="profile",
                          evidence_ids=[e2])
    rows = [i for i in await graph.insights("ws", "org1") if i.id == insight]
    assert rows[0].debate_status == "stale"


# ================= Specialists + recommender ==================================

class SpecialistLLM(ScriptedLLM):
    async def complete_json_route(self, prompt):
        if "pricing and value analyst" in prompt:
            ids = [line.split("]")[0].strip("[") for line in prompt.splitlines()
                   if line.startswith("[")]
            return {"insights": [{"title": "Premium pricing position",
                                  "body": "Tuition sits above market.",
                                  "kind": "finding", "claim_ids": ids[:1]}]}
        if "recommendation synthesizer" in prompt:
            cited = json.loads(prompt[prompt.index("cites: ") + 7:].splitlines()[0]
                               .replace("'", '"'))
            return {"recommendations": [
                {"title": "Publish value comparison", "body": "Justify premium.",
                 "claim_ids": cited},
                {"title": "Uncited padding", "body": "x", "claim_ids": ["bogus"]}]}
        return await super().complete_json_route(prompt)


async def test_specialist_swarm_and_recommendations(graph):
    ctx = make_ctx(graph, SpecialistLLM())
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.edu/p", "tuition pricing evidence content")
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                          statement="Tuition is 450,000 PKR.", predicate="tuition",
                          value="450000", topic="pricing", evidence_ids=[e1])
    ids = await SPECIALISTS["pricing_specialist"].run(ctx, root_entity_id=root.id,
                                                      organization="Acme")
    assert len(ids) == 1
    await Critic().review_insights(ctx, ids)             # validate it
    recs = await Recommender().run(ctx, organization="Acme")
    assert len(recs) == 1                                # uncited one dropped
    rec = [i for i in await graph.insights("ws", "org1") if i.id == recs[0]][0]
    assert rec.kind.value == "recommendation" and rec.claim_ids
    # rule 5 chain: recommendation cites claims that cite evidence
    chain_claims = await graph.get_claims(rec.claim_ids)
    assert all(c.evidence_ids for c in chain_claims)


# ================= Playbooks ===================================================

async def test_playbooks_govern_budget_and_watched_predicates(graph):
    with pytest.raises(ValueError):
        get_playbook("nonexistent")
    pw = get_playbook("pricing_watch")
    ctx = make_ctx(graph, playbook=pw)
    assert pw.max_searches == 10 and pw.specialists == ("pricing_specialist",)

    # playbook-watched predicate produces a SIGNAL on supersession
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.edu/d", "discount ten percent content")
    e2 = await ev(ctx, "https://b.gov/d", "discount twenty percent content")
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                          statement="Discount is 10%.", predicate="discount",
                          value="10%", as_of="2025-01-01", topic="pricing",
                          evidence_ids=[e1])
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                          statement="Discount is 20%.", predicate="discount",
                          value="20%", as_of="2026-01-01", topic="pricing",
                          evidence_ids=[e2])
    # 'discount' is functional? No — unknown → multi-valued → no signal. Use the
    # playbook's watched FUNCTIONAL predicate instead: tuition.
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                          statement="Tuition is 400,000.", predicate="tuition",
                          value="400000", as_of="2025-01-01", topic="pricing",
                          evidence_ids=[e1])
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                          statement="Tuition is 450,000.", predicate="tuition",
                          value="450000", as_of="2026-01-01", topic="pricing",
                          evidence_ids=[e2])
    signals = [i for i in await graph.insights("ws", "org1")
               if i.kind.value == "signal"]
    assert any("tuition" in s.title for s in signals)


# ================= Reconciliation sweep (B6) ===================================

async def test_reconciliation_sweep_resolves_parallel_conflicts(graph):
    from app.graph.diff import reconcile
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.edu/1", "sweep evidence one content")
    e2 = await ev(ctx, "https://b.edu/2", "sweep evidence two content")
    # simulate the parallel-write blind spot: two contradictory ACTIVE claims
    # written directly at store level (as racing writers would leave them)
    from app.graph.ontology import Claim
    c1 = await graph.add_claim(Claim(id="", workspace_id="ws",
                                     subject_entity_id=root.id,
                                     statement="Employees 100.", predicate="employees",
                                     value="100", as_of="2025-01-01", topic="profile",
                                     evidence_ids=[e1]))
    c2 = await graph.add_claim(Claim(id="", workspace_id="ws",
                                     subject_entity_id=root.id,
                                     statement="Employees 200.", predicate="employees",
                                     value="200", as_of="2026-01-01", topic="profile",
                                     evidence_ids=[e2]))
    assert all(c.status == "active" for c in await graph.get_claims([c1, c2]))
    out = await reconcile(ctx, root.id)
    assert out["groups"] == 1 and out["superseded"] == 1
    assert (await graph.get_claims([c1]))[0].status == "superseded"
    assert (await graph.get_claims([c2]))[0].status == "active"


# ================= value_entity_id (B9) ========================================

async def test_value_entity_id_prevents_spelling_conflicts(graph):
    ctx = make_ctx(graph)
    acme = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    beta = await graph.resolve_entity("ws", "Beta University", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.com/1", "acquired evidence one content")
    e2 = await ev(ctx, "https://b.com/2", "acquired evidence two content")
    # functional entity-valued predicate, same entity under different spellings
    a = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=acme.id,
                              statement="Acquired by Beta University.",
                              predicate="acquired_by", value="Beta University",
                              value_entity_id=beta.id, topic="profile",
                              as_of="2025-01-01", evidence_ids=[e1])
    b = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=acme.id,
                              statement="Acquired by The Beta University.",
                              predicate="acquired_by", value="The Beta University",
                              value_entity_id=beta.id, topic="profile",
                              as_of="2026-01-01", evidence_ids=[e2])
    rows = await graph.get_claims([a, b])
    assert all(r.status == "active" for r in rows)   # same canonical entity: no war
    assert not [i for i in await graph.insights("ws", "org1")
                if i.kind.value == "dispute"]


# ================= Jobs reaper + event retention ===============================

async def test_reaper_and_event_retention(tmp_path):
    from app.db import session as db
    from app.graph.models import EventRow, JobRow
    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/d.db", use_alembic=False)
    async with db._sessionmaker() as s:
        s.add(JobRow(id="stale1", status="running", payload={}, result={},
                     heartbeat_at="2020-01-01T00:00:00+00:00",
                     created_at="2020-01-01T00:00:00+00:00"))
        s.add(EventRow(run_id="old", type="x", payload={},
                       at="2020-01-01T00:00:00+00:00"))
        s.add(EventRow(run_id="new", type="x", payload={},
                       at="2099-01-01T00:00:00+00:00"))
        await s.commit()
    assert await db.reap_stale_jobs() == 1
    row = await db.get_job("stale1")
    assert row.status == "failed" and "reaped" in row.error
    assert await db.prune_events(older_than_days=14) == 1
    assert await db.events_for_run("new")            # recent events survive


async def test_concurrent_adjudication_single_transition(graph):
    """Break-review fix: 5 simultaneous supersede calls on one claim leave
    exactly ONE transition row (history not polluted; state correct)."""
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.edu/1", "ceo alice content")
    e2 = await ev(ctx, "https://b.edu/2", "ceo bob content")
    a = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="CEO Alice.", predicate="ceo", value="Alice",
                              topic="profile", evidence_ids=[e1])
    b = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="CEO Bob.", predicate="ceo", value="Bob",
                              as_of="2026-06-01", topic="profile", evidence_ids=[e2])
    await asyncio.gather(*[graph.supersede_claim(a, b, run_id=f"r{i}", reason="test")
                          for i in range(5)])
    trans = await graph.transitions_for(a)
    supersede_rows = [t for t in trans if t["to"] == "superseded"]
    assert len(supersede_rows) == 1                    # history single-rowed
    assert (await graph.get_claims([a]))[0].status == "superseded"
