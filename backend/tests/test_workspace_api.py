"""Intelligence Workspace read API — dashboard, recommendation chain, claim
timeline, debate view, search, research history. All read-only; asserts the
new endpoints are wired to the frozen store/critic/transition infrastructure."""
import asyncio

import httpx
import pytest

from app.db import session as db
from app.graph.ontology import EntityType, TrustVector
from app.main import app
from app.tools.registry import Budget, ToolContext, registry
from app.core.ledger import CostLedger
from app.providers.llm.router import LLMRouter
from tests.fakes_v2 import FakeSearchV2, ScriptedLLM


@pytest.fixture
async def client(tmp_path):
    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/ws.db", use_alembic=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _seed(org_name="Acme University"):
    """Seed a twin with a recommendation chain, a dispute, and a superseded
    claim (timeline), directly through the graph + tools (no network)."""
    graph = db.graph()
    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, org_name)
    root = await graph.resolve_entity(db.DEFAULT_WORKSPACE_ID, org_name,
                                      EntityType.ORGANIZATION)
    await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, org_name,
                                        root_entity_id=root.id)
    ctx = ToolContext(workspace_id=db.DEFAULT_WORKSPACE_ID, run_id="seed",
                      graph=graph, search=FakeSearchV2(),
                      llm=LLMRouter(ScriptedLLM(), ledger=CostLedger(), run_id="seed"),
                      budget=Budget(max_searches=99, max_llm_calls=99),
                      organization_id=org.id)

    async def ev(url, content):
        return (await registry.invoke(ctx, "graph.ingest_evidence", url=url,
                                      title="t", content=content))["evidence_id"]

    # a functional claim that will be superseded (timeline)
    e_old = await ev("https://a.edu/old", "enrollment twenty thousand old")
    e_new = await ev("https://a.edu/new", "enrollment twenty five thousand new")
    old = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                statement="Enrollment 20,000.", predicate="enrollment",
                                value="20000", as_of="2024-01-01", topic="profile",
                                evidence_ids=[e_old])
    new = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                statement="Enrollment 25,000.", predicate="enrollment",
                                value="25000", as_of="2026-01-01", topic="profile",
                                evidence_ids=[e_new])

    # a validated insight + a recommendation citing the new claim (chain)
    ins = await registry.invoke(ctx, "graph.write_insight", kind="finding",
                                title="Enrollment growth",
                                body="Enrollment rose to 25,000.",
                                claim_ids=[new], authored_by="market_specialist",
                                trust=TrustVector(confidence=0.7))
    await registry.invoke(ctx, "graph.review_insight", insight_id=ins,
                          verdict="validated", rationale="supported")
    rec = await registry.invoke(ctx, "graph.write_insight", kind="recommendation",
                                title="Invest in capacity",
                                body="Growth supports expansion.",
                                claim_ids=[new], authored_by="recommender",
                                trust=TrustVector(confidence=0.7))

    # a dispute (strong vs weak on a functional predicate)
    es = [await ev(f"https://s{i}.edu/r", f"ranked twelve {i}") for i in range(3)]
    ew = await ev("https://x.wordpress.com/r", "blog ranked thirty")
    strong = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                   statement="Ranked 12th.", predicate="ranking",
                                   value="12", as_of="2026-01-01", topic="market",
                                   evidence_ids=es)
    weak = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                 statement="Ranked 30th.", predicate="ranking",
                                 value="30", as_of="2026-06-01", topic="market",
                                 evidence_ids=[ew])
    disputes = [i for i in await graph.insights(db.DEFAULT_WORKSPACE_ID, org.id)
                if i.kind.value == "dispute"]
    # record a run for research history
    import uuid as _uuid; await db.persist_v2_run(_uuid.uuid4().hex[:12], db.DEFAULT_WORKSPACE_ID, org.id,
                            {"organization": org_name}, {"platform_version": "x"},
                            {"total_usd": 0.0},
                            {"claims": 4, "recommendations": 1,
                             "playbook": {"id": "full_analysis", "version": "1.0.0"}})
    return {"org_id": org.id, "root": root.id, "old": old, "new": new,
            "rec": rec, "insight": ins, "dispute": disputes[0].id if disputes else None,
            "strong": strong, "weak": weak}


async def test_dashboard_aggregates_and_filters(client):
    s = await _seed()
    dash = (await client.get(f"/v2/twins/{s['org_id']}/dashboard")).json()
    assert dash["counts"]["recommendations"] == 1
    assert dash["counts"]["validated"] == 1
    assert dash["counts"]["disputes_open"] == 1
    assert dash["counts"]["runs"] == 1
    assert dash["research_history"][0]["playbook"]["id"] == "full_analysis"
    # every insight carries trust
    assert all("trust" in r for r in dash["recommendations"])
    # filter by playbook
    filt = (await client.get(f"/v2/twins/{s['org_id']}/dashboard",
                             params={"playbook": "competitor_scan"})).json()
    assert filt["counts"]["runs"] == 0
    # filter by status
    val = (await client.get(f"/v2/twins/{s['org_id']}/dashboard",
                            params={"status": "validated"})).json()
    assert val["counts"]["validated"] == 1 and val["counts"]["recommendations"] == 0


async def test_recommendation_chain_is_fully_navigable(client):
    s = await _seed()
    chain = (await client.get(
        f"/v2/twins/{s['org_id']}/recommendations/{s['rec']}/chain")).json()
    assert chain["recommendation"]["id"] == s["rec"]
    assert chain["claims"] and chain["claims"][0]["claim"]["id"] == s["new"]
    assert chain["claims"][0]["evidence"]                    # claim → evidence
    supporting = [i["id"] for i in chain["supporting_insights"]]
    assert s["insight"] in supporting                        # shared-claim insight
    assert (await client.get(
        f"/v2/twins/{s['org_id']}/recommendations/bogus/chain")).status_code == 404


async def test_claim_timeline_shows_transitions(client):
    s = await _seed()
    tl = (await client.get(f"/v2/claims/{s['old']}/timeline")).json()
    reasons = [t["reason"] for t in tl["timeline"]]
    assert reasons[0] == "created"
    assert "conflict_lost" in reasons                        # superseded transition
    assert tl["claim"]["status"] == "superseded"
    assert all("at" in t for t in tl["timeline"])            # timestamps present


async def test_debate_view(client):
    s = await _seed()
    detail = (await client.get(
        f"/v2/twins/{s['org_id']}/disputes/{s['dispute']}").json() if False else
        (await client.get(f"/v2/twins/{s['org_id']}/disputes/{s['dispute']}")).json())
    assert len(detail["sides"]) == 2
    for side in detail["sides"]:
        assert "trust" in side["claim"] and side["evidence"] is not None
    assert detail["status"] in ("unreviewed", "deferred", "resolved")


async def test_global_search(client):
    s = await _seed()
    res = (await client.get("/v2/search",
                            params={"q": "Acme", "org_id": s["org_id"]})).json()
    assert any(e["name"] == "Acme University" for e in res["entities"])
    res2 = (await client.get("/v2/search",
                             params={"q": "capacity", "org_id": s["org_id"]})).json()
    assert any(r["id"] == s["rec"] for r in res2["recommendations"])


async def test_organizations_and_recommendations_list(client):
    s = await _seed()
    orgs = (await client.get("/v2/organizations")).json()
    assert any(o["id"] == s["org_id"] for o in orgs)
    recs = (await client.get(f"/v2/twins/{s['org_id']}/recommendations")).json()
    assert len(recs) == 1 and recs[0]["kind"] == "recommendation"


async def test_workspace_reads_are_pure(client):
    """Read-path purity: dashboard/chain/timeline/search never mutate."""
    from sqlalchemy import func, select
    from app.graph.models import ClaimRow, InsightRow
    s = await _seed()

    async def counts():
        async with db._sessionmaker() as sess:
            c = (await sess.execute(select(func.count()).select_from(ClaimRow))).scalar()
            i = (await sess.execute(select(func.count()).select_from(InsightRow))).scalar()
            return c, i

    before = await counts()
    for _ in range(3):
        await client.get(f"/v2/twins/{s['org_id']}/dashboard")
        await client.get(f"/v2/twins/{s['org_id']}/recommendations/{s['rec']}/chain")
        await client.get(f"/v2/claims/{s['old']}/timeline")
        await client.get("/v2/search", params={"q": "Acme", "org_id": s["org_id"]})
    assert await counts() == before


async def test_cross_org_detail_access_is_denied(client):
    """Audit fix: recommendation chain, dispute detail, and insight detail must
    be scoped to the owning organization — no cross-twin data exposure."""
    a = await _seed("Acme University")
    b = await _seed("Beta College")
    assert a["org_id"] != b["org_id"]
    # A's recommendation requested under B → 404
    r = await client.get(f"/v2/twins/{b['org_id']}/recommendations/{a['rec']}/chain")
    assert r.status_code == 404
    # A's dispute requested under B → 404
    r = await client.get(f"/v2/twins/{b['org_id']}/disputes/{a['dispute']}")
    assert r.status_code == 404
    # each org's dashboard only contains its own recommendations
    da = (await client.get(f"/v2/twins/{a['org_id']}/dashboard")).json()
    ids = [x["id"] for x in da["recommendations"]]
    assert a["rec"] in ids and b["rec"] not in ids
    # own-org access still works
    assert (await client.get(
        f"/v2/twins/{a['org_id']}/recommendations/{a['rec']}/chain")).status_code == 200
    assert (await client.get(
        f"/v2/twins/{a['org_id']}/disputes/{a['dispute']}")).status_code == 200


async def test_since_filter_includes_same_day(client):
    """Audit fix: date-only 'since' must not drop same-day items via string
    comparison against full ISO timestamps."""
    s = await _seed()
    dash = (await client.get(f"/v2/twins/{s['org_id']}/dashboard")).json()
    today = dash["research_history"][0]["created_at"][:10]
    filtered = (await client.get(f"/v2/twins/{s['org_id']}/dashboard",
                                 params={"since": today})).json()
    assert filtered["counts"]["validated"] == dash["counts"]["validated"]
    assert filtered["counts"]["runs"] == dash["counts"]["runs"]


async def test_executive_briefing_aggregates_real_data(client):
    """The workspace briefing aggregates real per-twin graph data — priority
    feed and discoveries are grounded in actual insights/disputes, never faked."""
    a = await _seed("Acme University")
    b = await _seed("Beta College")
    brief = (await client.get("/v2/briefing")).json()
    assert brief["has_data"] is True
    # both twins present
    names = {t["name"] for t in brief["twins"]}
    assert {"Acme University", "Beta College"} <= names
    # totals aggregate across twins (each seed: 1 validated, 1 rec, 1 open dispute)
    assert brief["totals"]["recommendations"] >= 2
    assert brief["totals"]["validated"] >= 2
    assert brief["totals"]["disputes_open"] >= 2
    # priority feed carries real items with confidence + evidence + action
    assert len(brief["priority_feed"]) > 0
    for item in brief["priority_feed"]:
        assert item["kind"] in ("dispute", "signal", "recommendation")
        assert "confidence" in item and "action" in item
        assert item["org_name"] in names
    # feed is severity-then-confidence ordered
    sev_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    ranks = [sev_rank[p["severity"]] for p in brief["priority_feed"]]
    assert ranks == sorted(ranks)
    # discoveries reference real insights
    assert all("title" in d and "at" in d for d in brief["discoveries"])


async def test_briefing_empty_workspace_is_honest(client):
    """No twins → briefing says so rather than inventing data (Rule 4)."""
    brief = (await client.get("/v2/briefing")).json()
    assert brief["has_data"] is False
    assert brief["twins"] == []
    assert brief["priority_feed"] == []
    assert brief["totals"]["validated"] == 0


async def test_competitors_endpoint_is_evidence_backed(client):
    """Competitor intelligence comes from real graph edges → entities → claims →
    evidence. No fabricated fields; confidence is derived from claim trust."""
    from app.graph.ontology import EntityType
    from app.tools.registry import Budget, ToolContext, registry
    from app.core.ledger import CostLedger
    from app.providers.llm.router import LLMRouter
    import app.tools.graph_tools  # noqa

    graph = db.graph()
    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Acme Corp")
    root = await graph.resolve_entity(db.DEFAULT_WORKSPACE_ID, "Acme Corp",
                                      EntityType.ORGANIZATION)
    await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Acme Corp",
                                        root_entity_id=root.id)
    ctx = ToolContext(workspace_id=db.DEFAULT_WORKSPACE_ID, run_id="t", graph=graph,
                      search=FakeSearchV2(),
                      llm=LLMRouter(ScriptedLLM(), ledger=CostLedger(), run_id="t"),
                      budget=Budget(max_searches=99, max_llm_calls=99),
                      organization_id=org.id)
    e = (await registry.invoke(ctx, "graph.ingest_evidence",
                               url="https://rival.com/x", title="t",
                               content="rival evidence content"))["evidence_id"]
    rival = await graph.resolve_entity(db.DEFAULT_WORKSPACE_ID, "Rival Inc",
                                       EntityType.ORGANIZATION)
    await registry.invoke(ctx, "graph.write_edge", source_entity_id=root.id,
                          target_entity_id=rival.id, relation="competitor_of",
                          evidence_ids=[e])
    await registry.invoke(ctx, "graph.write_claim", subject_entity_id=rival.id,
                          statement="Rival pricing is 999.", predicate="pricing",
                          value="999", topic="pricing", evidence_ids=[e])

    res = (await client.get(f"/v2/twins/{org.id}/competitors")).json()
    assert res["has_data"] is True
    assert len(res["competitors"]) == 1
    comp = res["competitors"][0]
    assert comp["name"] == "Rival Inc"
    assert comp["claim_count"] == 1
    assert comp["evidence_count"] == 1
    assert 0 < comp["confidence"] <= 1          # derived, not fabricated
    assert "pricing" in comp["profile"]         # real topic bucket
    assert comp["profile"]["pricing"][0]["value"] == "999"


async def test_competitors_empty_is_honest(client):
    """A twin with no competitor edges reports has_data False (Rule 2)."""
    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Lonely Inc")
    from app.graph.ontology import EntityType
    root = await db.graph().resolve_entity(db.DEFAULT_WORKSPACE_ID, "Lonely Inc",
                                           EntityType.ORGANIZATION)
    await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Lonely Inc",
                                        root_entity_id=root.id)
    res = (await client.get(f"/v2/twins/{org.id}/competitors")).json()
    assert res["has_data"] is False
    assert res["competitors"] == []
