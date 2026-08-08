"""Mandated tests: entity extraction, claim extraction, research loop,
chat retrieval, Tool Layer budget enforcement."""
import time

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.chat.analyst import AnalystChat
from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import EntityType
from app.graph.store import IntelligenceGraph
from app.providers.llm.router import LLMRouter
from app.research.loop import ResearchLoop
from app.tools.registry import Budget, BudgetExceeded, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
import app.tools.web_tools    # noqa: F401
from tests.fakes_v2 import UNI, FakeSearchV2, ScriptedLLM


@pytest.fixture
async def graph(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/graph.db")
    @event.listens_for(engine.sync_engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")
    import app.graph.models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield IntelligenceGraph(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def make_ctx(graph, llm, org_id="org1") -> ToolContext:
    return ToolContext(workspace_id="ws", run_id="test", graph=graph,
                       search=FakeSearchV2(),
                       llm=LLMRouter(llm, ledger=CostLedger(), run_id="test"),
                       budget=Budget(max_searches=50, max_llm_calls=50),
                       organization_id=org_id)


async def test_extraction_creates_entities_claims_edges_and_drops_unevidenced(graph):
    from app.graph.ontology import Evidence
    from app.research.extraction import extract
    root = await graph.resolve_entity("ws", UNI, EntityType.ORGANIZATION)
    ctx = make_ctx(graph, ScriptedLLM())
    e1 = Evidence(id="", url="https://acme.edu/about", canonical_url="https://acme.edu/about",
                  domain="acme.edu", title="About", content="founded 2004 " * 20)
    e2 = Evidence(id="", url="https://news.example.com/r", canonical_url="https://news.example.com/r",
                  domain="news.example.com", title="Rankings", content="25000 students beta " * 20)
    for e in (e1, e2):
        e.id, _ = await graph.ingest_evidence(e)
    result = await extract(ctx, subject_name=UNI, subject_entity_id=root.id,
                           topic="profile", evidence=[e1, e2])

    assert len(result["claims"]) == 3          # 4 proposed, 1 unevidenced dropped
    claims = await graph.get_claims(result["claims"])
    founded = next(c for c in claims if "founded" in c.statement)
    assert founded.kind.value == "event" and founded.evidence_ids == [e1.id]
    assert founded.predicate == "founded"      # v3: structural key present
    enroll = next(c for c in claims if "25,000" in c.statement)
    assert set(enroll.evidence_ids) == {e1.id, e2.id}
    assert enroll.trust.evidence_count == 2 and enroll.trust.corroboration > 0

    beta_claim = next(c for c in claims if "Beta" in c.statement)
    beta = await graph.get_entity(beta_claim.subject_entity_id)
    assert beta.name == "Beta University"      # cross-entity claim attached (moat)

    edges = await graph.edges_from(root.id, relation="competitor_of")
    assert len(edges) == 1 and edges[0].evidence_ids == [e2.id]
    # C5-B: edge is claim-backed; backing claim is a real, evidenced claim
    assert edges[0].claim_id is not None
    backing = (await graph.get_claims([edges[0].claim_id]))[0]
    assert backing.predicate == "competitor_of" and backing.status == "active"

    # S3: extraction cache — re-extracting the same evidence is a no-op
    again = await extract(ctx, subject_name=UNI, subject_entity_id=root.id,
                          topic="profile", evidence=[e1, e2])
    assert again["cache_hits"] == 2 and again["raw_counts"]["claims"] == 0


async def test_research_loop_end_to_end(graph):
    root = await graph.resolve_entity("ws", UNI, EntityType.ORGANIZATION)
    llm = ScriptedLLM()
    ctx = make_ctx(graph, llm)

    # scripted specialist must cite real ids → run loop in two steps:
    # first pass creates claims; specialist fake cites them via hook below
    loop = ResearchLoop(max_hypotheses=2)

    # monkey-patch specialist fake to cite whatever profile claims exist
    orig = ScriptedLLM.complete_json_route
    async def routed(self, prompt):
        if "competitive intelligence specialist" in prompt:
            claims = await graph.claims("ws", limit=5)
            self.insight_claim_ids = [c.id for c in claims[:2]]
        return await orig(self, prompt)
    ScriptedLLM.complete_json_route = routed
    try:
        stats = await loop.run(ctx, brief={"organization": UNI, "objectives": ["competitors"]},
                               root_entity_id=root.id)
    finally:
        ScriptedLLM.complete_json_route = orig

    assert stats["claims"] > 0 and stats["verified_failed"] == 0
    assert stats["evidence_reused"] > 0        # same fake pages dedup into corpus
    assert len(stats["hypotheses"]) == 2
    assert stats["insights"], "specialist wrote at least one insight"
    insights = await graph.insights("ws", "org1")
    assert insights and insights[0].claim_ids   # traceability chain intact
    cov = await graph.coverage("ws", root.id)
    assert cov.get("profile", {}).get("claims", 0) > 0


async def test_delta_research_skips_known_profile(graph):
    """Rule 4: second run must not re-research a known profile."""
    root = await graph.resolve_entity("ws", UNI, EntityType.ORGANIZATION)
    llm = ScriptedLLM()
    ctx = make_ctx(graph, llm)
    loop = ResearchLoop(max_hypotheses=1)
    brief = {"organization": UNI, "objectives": []}

    orig = ScriptedLLM.complete_json_route
    async def routed(self, prompt):
        if "competitive intelligence specialist" in prompt:
            claims = await graph.claims("ws", limit=2)
            self.insight_claim_ids = [c.id for c in claims]
        return await orig(self, prompt)
    ScriptedLLM.complete_json_route = routed
    try:
        await loop.run(ctx, brief=brief, root_entity_id=root.id)
        searches_after_first = len(ctx.search.queries)
        ctx2 = make_ctx(graph, llm)
        await loop.run(ctx2, brief=brief, root_entity_id=root.id)
    finally:
        ScriptedLLM.complete_json_route = orig
    # second run: no profile seed searches (2 fewer), only hypothesis queries
    assert len(ctx2.search.queries) < searches_after_first


async def test_budget_stops_searches(graph):
    ctx = make_ctx(graph, ScriptedLLM())
    ctx.budget = Budget(max_searches=1)
    await registry.invoke(ctx, "web.search", query="q1")
    with pytest.raises(BudgetExceeded):
        await registry.invoke(ctx, "web.search", query="q2")


async def test_chat_cites_only_real_claims_and_uses_tools(graph):
    root = await graph.resolve_entity("ws", UNI, EntityType.ORGANIZATION)
    from app.graph.ontology import Claim, Evidence, TrustVector
    e = Evidence(id="", url="https://acme.edu/fees", canonical_url="https://acme.edu/fees",
                 domain="acme.edu", title="Fees", content="Tuition is 450k PKR.")
    e.id, _ = await graph.ingest_evidence(e)
    cid = await graph.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=root.id,
                                      statement="Acme tuition is 450,000 PKR per year.",
                                      topic="pricing", evidence_ids=[e.id],
                                      trust=TrustVector(confidence=0.8)))
    llm = ScriptedLLM(chat_payload={
        "answer": f"Tuition is 450,000 PKR [C:{cid}]. Also fake [C:deadbeef].",
        "cited_claim_ids": [cid, "deadbeef"],
        "needs_research": False, "proposed_research": None})
    ctx = make_ctx(graph, llm)
    ans = await AnalystChat().ask(ctx, organization=UNI, root_entity_id=root.id,
                                  question="What is the tuition?")
    assert len(ans.citations) == 1 and ans.citations[0]["claim_id"] == cid
    assert "[C:deadbeef]" not in ans.answer          # invented citation stripped
    assert ans.citations[0]["evidence"][0]["url"] == "https://acme.edu/fees"


async def test_chat_empty_graph_proposes_research(graph):
    root = await graph.resolve_entity("ws", "Ghost Corp", EntityType.ORGANIZATION)
    ctx = make_ctx(graph, ScriptedLLM())
    ans = await AnalystChat().ask(ctx, organization="Ghost Corp",
                                  root_entity_id=root.id, question="revenue?")
    assert ans.needs_research is True and not ans.citations
