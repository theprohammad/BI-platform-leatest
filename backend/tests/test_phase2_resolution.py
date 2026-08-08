"""S4 entity resolution: layered resolver with industry fixtures.
PRECISION GATE (frozen invariant): zero false merges allowed. Recall reported.
"""
import asyncio
import os

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import Claim, EntityType, Evidence
from app.graph.store import IntelligenceGraph
from app.providers.llm.base import LLMResult
from app.providers.llm.router import LLMRouter
from app.tools.registry import Budget, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
from tests.fakes_v2 import FakeSearchV2


# ---- fixtures: SAME organization under different surface forms ---------------
SAME = [
    ("University of Central Punjab", "The University of Central Punjab"),
    ("Superior University Lahore", "Superior University, Lahore"),
    ("Lahore University of Management Sciences", "Lahore University of Management Sciences (LUMS)"),
    ("Acme Software Pvt Ltd", "Acme Software (Pvt) Ltd."),
]
# ---- fixtures: DIFFERENT organizations that look confusable ------------------
DIFFERENT = [
    ("Punjab University", "University of Central Punjab"),
    ("Superior University Lahore", "Superior College Lahore"),
    ("Lahore School of Economics", "Lahore College for Women University"),
    ("Acme Software Pvt Ltd", "Acme Textiles Pvt Ltd"),
    ("Beta University", "Delta University"),
]


class AdjudicatorLLM:
    """Extract-tier adjudicator: token-subset heuristic stands in for the model;
    only ever CONFIRMS (never proposes) — mirrors the resolver contract."""
    async def complete_json(self, *, model, system, prompt, temperature, timeout):
        import json, re
        a = re.search(r'A: "(.+?)"', prompt).group(1).lower()
        b = re.search(r'B: "(.+?)"', prompt).group(1).lower()
        stop = {"the", "of", "pvt", "ltd", "(pvt)", "ltd.", "(lums)"}
        ta = {t.strip(".,()") for t in a.split()} - stop
        tb = {t.strip(".,()") for t in b.split()} - stop
        same = ta == tb or (ta <= tb or tb <= ta) and len(ta & tb) >= 3
        return LLMResult(json.dumps({"same": bool(same), "confidence": 0.95 if same else 0.2}),
                         model, 10, 5)


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


@pytest.fixture
def auto_merge_on(monkeypatch):
    monkeypatch.setenv("RESOLUTION_AUTO_MERGE", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("RESOLUTION_AUTO_MERGE", raising=False)
    get_settings.cache_clear()


def make_ctx(graph) -> ToolContext:
    return ToolContext(workspace_id="ws", run_id="test", graph=graph,
                       search=FakeSearchV2(),
                       llm=LLMRouter(AdjudicatorLLM(), ledger=CostLedger(), run_id="test"),
                       budget=Budget(), organization_id="org1")


async def test_resolution_precision_and_recall(graph, auto_merge_on):
    ctx = make_ctx(graph)
    false_merges, merges = 0, 0
    for a, b in SAME:
        ea = await registry.invoke(ctx, "graph.resolve_entity", name=a,
                                   type=EntityType.ORGANIZATION)
        eb = await registry.invoke(ctx, "graph.resolve_entity", name=b,
                                   type=EntityType.ORGANIZATION)
        if ea.id == eb.id:
            merges += 1
    for a, b in DIFFERENT:
        ea = await registry.invoke(ctx, "graph.resolve_entity", name=a,
                                   type=EntityType.ORGANIZATION)
        eb = await registry.invoke(ctx, "graph.resolve_entity", name=b,
                                   type=EntityType.ORGANIZATION)
        if ea.id == eb.id:
            false_merges += 1
    assert false_merges == 0, "PRECISION GATE VIOLATED: false merge occurred"
    assert merges >= 3, f"recall too low: {merges}/{len(SAME)} same-pairs merged"


async def test_auto_merge_off_records_candidates_only(graph):
    """Default (prod) posture: no auto-merge; ambiguity → review-queue rows."""
    get_settings.cache_clear()
    ctx = make_ctx(graph)
    a = await registry.invoke(ctx, "graph.resolve_entity",
                              name="University of Central Punjab",
                              type=EntityType.ORGANIZATION)
    b = await registry.invoke(ctx, "graph.resolve_entity",
                              name="The University of Central Punjab",
                              type=EntityType.ORGANIZATION)
    assert a.id != b.id                                   # never merged silently
    from sqlalchemy import select, func
    from app.graph.models import EntityMergeCandidateRow
    async with graph._session_for_reads() as s:
        n = (await s.execute(select(func.count())
                             .select_from(EntityMergeCandidateRow))).scalar()
    assert n >= 1                                          # but surfaced for review


async def test_merge_repoints_and_handles_identity_collision(graph):
    ent_a = await graph.resolve_entity("ws", "Acme University", EntityType.ORGANIZATION)
    ent_b = await graph.resolve_entity("ws", "The Acme University", EntityType.ORGANIZATION)
    ev1, _ = await graph.ingest_evidence(Evidence(id="", url="https://a.edu/1",
                                                  canonical_url="https://a.edu/1",
                                                  domain="a.edu", title="t",
                                                  content="unique fact one"))
    ev2, _ = await graph.ingest_evidence(Evidence(id="", url="https://b.gov/2",
                                                  canonical_url="https://b.gov/2",
                                                  domain="b.gov", title="t",
                                                  content="same statement other src"))
    # unique claim on loser + identical-statement claim on both (collision case)
    only_b = await graph.add_claim(Claim(id="", workspace_id="ws",
                                         subject_entity_id=ent_b.id,
                                         statement="Only-on-B fact.", topic="profile",
                                         evidence_ids=[ev1]))
    on_a = await graph.add_claim(Claim(id="", workspace_id="ws",
                                       subject_entity_id=ent_a.id,
                                       statement="Founded in 2004.", topic="profile",
                                       evidence_ids=[ev1]))
    on_b = await graph.add_claim(Claim(id="", workspace_id="ws",
                                       subject_entity_id=ent_b.id,
                                       statement="Founded in 2004.", topic="profile",
                                       evidence_ids=[ev2]))
    result = await graph.merge_entities("ws", loser_id=ent_b.id, winner_id=ent_a.id,
                                        score=0.95, method="manual")
    assert result["claims_moved"] == 1 and result["claims_collided"] == 1
    moved = (await graph.get_claims([only_b]))[0]
    assert moved.subject_entity_id == ent_a.id            # repointed + identity rehashed
    collided = (await graph.get_claims([on_b]))[0]
    assert collided.status == "superseded" and collided.superseded_by == on_a
    winner_claim = (await graph.get_claims([on_a]))[0]
    assert set(winner_claim.evidence_ids) >= {ev1}        # junction is truth
    from sqlalchemy import select
    from app.graph.models import ClaimEvidenceRow
    async with graph._session_for_reads() as s:
        evs = {r for (r,) in (await s.execute(
            select(ClaimEvidenceRow.evidence_id)
            .where(ClaimEvidenceRow.claim_id == on_a))).all()}
    assert evs == {ev1, ev2}                              # evidence union
    # tombstone: resolving loser name reaches winner
    again = await graph.resolve_entity("ws", "The Acme University")
    assert again.id == ent_a.id


async def test_concurrent_merges_same_pair_single_outcome(graph):
    a = await graph.resolve_entity("ws", "Gamma University", EntityType.ORGANIZATION)
    b = await graph.resolve_entity("ws", "The Gamma University", EntityType.ORGANIZATION)
    results = await asyncio.gather(
        *(graph.merge_entities("ws", loser_id=b.id, winner_id=a.id,
                               score=0.95, method="manual") for _ in range(5)),
        return_exceptions=True)
    ok = [r for r in results if isinstance(r, dict)]
    assert ok, "at least one merge must succeed"
    final = await graph.resolve_entity("ws", "The Gamma University")
    assert final.id == a.id
