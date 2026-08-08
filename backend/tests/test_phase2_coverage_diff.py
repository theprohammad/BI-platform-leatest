"""S1 quality coverage + S7 diff engine scenario tests (spec §7)."""
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import Claim, ClaimKind, EntityType, Evidence, TrustVector
from app.graph.store import IntelligenceGraph
from app.providers.llm.router import LLMRouter
from app.tools.registry import Budget, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
import app.tools.web_tools    # noqa: F401
from tests.fakes_v2 import FakeSearchV2, ScriptedLLM


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


def make_ctx(graph, org_id="org1") -> ToolContext:
    return ToolContext(workspace_id="ws", run_id="test", graph=graph,
                       search=FakeSearchV2(),
                       llm=LLMRouter(ScriptedLLM(), ledger=CostLedger(), run_id="test"),
                       budget=Budget(max_searches=50, max_llm_calls=50),
                       organization_id=org_id)


async def seed_evidence(graph, content, url="https://x.edu/a", domain="x.edu",
                        published=None):
    ev = Evidence(id="", url=url, canonical_url=url, domain=domain, title="t",
                  content=content, published_date=published)
    ev_id, _ = await graph.ingest_evidence(ev)
    return ev_id


# ---------------- S1: quality coverage --------------------------------------

async def test_coverage_quality_vector(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await seed_evidence(graph, "acme tuition is 450k", url="https://acme.edu/f",
                             domain="acme.edu")
    e2 = await seed_evidence(graph, "tuition at acme confirmed 450k",
                             url="https://news.example.com/t", domain="news.example.com")
    c1 = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                               statement="Acme tuition is 450,000 PKR.",
                               predicate="tuition", value="450000",
                               topic="pricing", evidence_ids=[e1, e2])
    c2 = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                               statement="Acme offers 40 programs.",
                               topic="pricing", evidence_ids=[e1])
    await graph.set_claim_status([c2], "unsupported")

    cov = await registry.invoke(ctx, "graph.coverage", subject_entity_id=root.id)
    pricing = cov["pricing"]
    assert pricing["claims"] == 1                       # active only
    assert pricing["distinct_domains"] == 2             # quality, not volume
    assert pricing["unsupported_rate"] == 0.5           # 1 of 2 failed verification
    assert 0 < pricing["mean_confidence"] <= 1
    assert pricing["open_disputes"] == 0
    assert pricing["staleness_days"] < 1                # created just now
    # read-time freshness present on claims (B9)
    claim = (await graph.get_claims([c1]))[0]
    assert claim.trust.freshness == 1.0


# ---------------- S7: diff engine scenario table ------------------------------

async def scenario(graph, ctx, root, *, old_domain, new_domain, old_asof, new_asof):
    e_old = await seed_evidence(graph, f"enrollment was reported {old_asof}",
                                url=f"https://{old_domain}/a", domain=old_domain,
                                published=old_asof)
    e_new = await seed_evidence(graph, f"enrollment now reported {new_asof}",
                                url=f"https://{new_domain}/b", domain=new_domain,
                                published=new_asof)
    old_id = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                   statement=f"Enrollment is 20,000 ({old_asof}).",
                                   predicate="enrollment", value="20000",
                                   topic="profile", as_of=old_asof, evidence_ids=[e_old])
    new_id = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                   statement=f"Enrollment is 25,000 ({new_asof}).",
                                   predicate="enrollment", value="25000",
                                   topic="profile", as_of=new_asof, evidence_ids=[e_new])
    return old_id, new_id


async def test_diff_supersedes_when_newer_and_trusted(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    old_id, new_id = await scenario(graph, ctx, root,
                                    old_domain="acme.edu", new_domain="news.gov",
                                    old_asof="2024-01-01", new_asof="2026-01-01")
    old = (await graph.get_claims([old_id]))[0]
    assert old.status == "superseded" and old.superseded_by == new_id
    active = await graph.claims("ws", subject_entity_id=root.id, topic="profile")
    assert {c.id for c in active} == {new_id}
    # watched predicate → signal insight emitted
    signals = [i for i in await graph.insights("ws", "org1") if i.kind.value == "signal"]
    assert signals and "enrollment" in signals[0].title


async def test_diff_disputes_when_trust_gap(graph):
    """Newer but much weaker source must NOT silently win — dispute instead."""
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    old_id, new_id = await scenario(graph, ctx, root,
                                    old_domain="acme.edu",       # tier 0.9
                                    new_domain="blogspot.com",   # tier 0.35 → gap > 0.15
                                    old_asof="2026-01-01", new_asof="2026-06-01")
    old = (await graph.get_claims([old_id]))[0]
    assert old.status == "active"                       # incumbent survives
    disputes = [i for i in await graph.insights("ws", "org1") if i.kind.value == "dispute"]
    assert disputes and set(disputes[0].claim_ids) == {old_id, new_id}


async def test_diff_noop_on_equal_values_and_no_predicate(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await seed_evidence(graph, "founded 2004 alpha")
    e2 = await seed_evidence(graph, "founded 2004 beta", url="https://y.gov/b", domain="y.gov")
    a = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="Founded in 2004.", predicate="founded",
                              value="2004", topic="profile", evidence_ids=[e1])
    b = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="Established 2004.", predicate="founded",
                              value="2004", topic="profile", evidence_ids=[e2])
    assert (await graph.get_claims([a]))[0].status == "active"
    assert (await graph.get_claims([b]))[0].status == "active"   # same value → no-op
    # prose-only claims never structurally diff (fail-safe)
    c = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="A narrative statement.", topic="profile",
                              evidence_ids=[e1])
    assert (await graph.get_claims([c]))[0].status == "active"
    assert not [i for i in await graph.insights("ws", "org1") if i.kind.value == "dispute"]


async def test_change_report(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    since = "2000-01-01T00:00:00+00:00"
    await scenario(graph, ctx, root, old_domain="acme.edu", new_domain="news.gov",
                   old_asof="2024-01-01", new_asof="2026-01-01")
    from app.graph.diff import build_change_report
    report = await build_change_report(ctx, root.id, since)
    assert report["new_claims"] >= 1
    assert report["supersessions"] and report["supersessions"][0]["predicate"] == "enrollment"
    assert report["supersessions"][0]["old_value"] == "20000"
    assert report["signals"]
