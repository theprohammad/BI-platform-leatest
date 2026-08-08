"""S5 retrieval evaluation (spec §7): ≥40 generated cases over a seeded graph.
CI GATE: recall@8 ≥ 0.85 for hybrid. Also: per-leg failure degradation and
hybrid ≥ keyword baseline.
"""
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import EntityType
from app.graph.store import IntelligenceGraph
from app.providers.llm.router import LLMRouter
from app.tools.registry import Budget, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
from tests.fakes_v2 import FakeSearchV2, ScriptedLLM

# ---- seeded world: 3 orgs × facts; questions template over them --------------
ORGS = {
    "Acme University": [
        ("founded", "2004", "Acme University was founded in 2004.", "profile"),
        ("enrollment", "25000", "Acme University enrolls 25,000 students.", "profile"),
        ("tuition", "450000", "Acme University tuition is 450,000 PKR per year.", "pricing"),
        ("campus_count", "3", "Acme University operates 3 campuses in Lahore.", "profile"),
        ("ranking", "12", "Acme University is ranked 12th nationally by HEC.", "market"),
    ],
    "Beta University": [
        ("founded", "1998", "Beta University was founded in 1998.", "profile"),
        ("enrollment", "18000", "Beta University enrolls 18,000 students.", "profile"),
        ("tuition", "380000", "Beta University tuition is 380,000 PKR per year.", "pricing"),
        ("ranking", "20", "Beta University is ranked 20th nationally by HEC.", "market"),
    ],
    "Gamma Institute": [
        ("founded", "2015", "Gamma Institute was founded in 2015.", "profile"),
        ("enrollment", "4000", "Gamma Institute enrolls 4,000 students.", "profile"),
        ("tuition", "520000", "Gamma Institute tuition is 520,000 PKR per year.", "pricing"),
    ],
}

QUESTION_TEMPLATES = {
    "founded": ["When was {org} founded?", "{org} founding year",
                "how old is {org}", "establishment date of {org}"],
    "enrollment": ["How many students does {org} have?", "{org} enrollment numbers",
                   "student population at {org}"],
    "tuition": ["What is the tuition at {org}?", "{org} fees per year",
                "how expensive is {org}", "cost of studying at {org}"],
    "campus_count": ["How many campuses does {org} have?",
                     "{org} campus locations count"],
    "ranking": ["What is {org} ranked?", "{org} national ranking",
                "where does {org} stand in HEC rankings"],
}


@pytest.fixture
async def seeded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    @event.listens_for(engine.sync_engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")
    import app.graph.models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    graph = IntelligenceGraph(async_sessionmaker(engine, expire_on_commit=False))
    ctx = ToolContext(workspace_id="ws", run_id="eval", graph=graph,
                      search=FakeSearchV2(),
                      llm=LLMRouter(ScriptedLLM(), ledger=CostLedger(), run_id="eval"),
                      budget=Budget(max_searches=999))
    expected: dict[tuple, str] = {}
    for org, facts in ORGS.items():
        ent = await registry.invoke(ctx, "graph.resolve_entity", name=org,
                                    type=EntityType.ORGANIZATION)
        for predicate, value, statement, topic in facts:
            out = await registry.invoke(
                ctx, "graph.ingest_evidence",
                url=f"https://{org.split()[0].lower()}.edu/{predicate}",
                title=f"{org} {predicate}", content=statement + " " + statement)
            claim_id = await registry.invoke(
                ctx, "graph.write_claim", subject_entity_id=ent.id,
                statement=statement, predicate=predicate, value=value,
                topic=topic, evidence_ids=[out["evidence_id"]])
            expected[(org, predicate)] = claim_id
    yield graph, expected
    await engine.dispose()


def cases():
    out = []
    for org, facts in ORGS.items():
        for predicate, *_ in facts:
            for template in QUESTION_TEMPLATES.get(predicate, []):
                out.append((template.format(org=org), org, predicate))
    return out


async def test_eval_set_size_and_recall_at_8(seeded):
    graph, expected = seeded
    eval_cases = cases()
    assert len(eval_cases) >= 40, f"eval set too small: {len(eval_cases)}"
    hits = 0
    for question, org, predicate in eval_cases:
        results = await graph.search_claims("ws", question, limit=8)
        if expected[(org, predicate)] in {c.id for c in results}:
            hits += 1
    recall = hits / len(eval_cases)
    assert recall >= 0.85, f"recall@8 gate failed: {recall:.2f} ({hits}/{len(eval_cases)})"


async def test_hybrid_not_worse_than_keyword(seeded, monkeypatch):
    graph, expected = seeded
    eval_cases = cases()

    async def recall_with(strategy):
        monkeypatch.setenv("RETRIEVAL_STRATEGY", strategy)
        get_settings.cache_clear()
        if hasattr(graph, "_retriever"):
            del graph._retriever
        hits = 0
        for question, org, predicate in eval_cases:
            results = await graph.search_claims("ws", question, limit=8)
            hits += expected[(org, predicate)] in {c.id for c in results}
        return hits / len(eval_cases)

    keyword = await recall_with("keyword")
    hybrid = await recall_with("hybrid")
    monkeypatch.delenv("RETRIEVAL_STRATEGY", raising=False)
    get_settings.cache_clear()
    assert hybrid >= keyword, f"hybrid ({hybrid:.2f}) worse than keyword ({keyword:.2f})"


async def test_leg_failure_degrades_not_dies(seeded, monkeypatch):
    graph, expected = seeded
    from app.graph.retrieval import HybridRetriever
    retriever = HybridRetriever(graph)

    async def broken(*a, **k):
        raise RuntimeError("vector index down")
    monkeypatch.setattr(retriever, "_leg_vector", broken)
    results = await retriever.search("ws", "When was Acme University founded?", limit=8)
    assert expected[("Acme University", "founded")] in {c.id for c in results}
