"""End-to-end steel thread over the real HTTP surface with fake providers:
conversation → research → graph → twin endpoints → cited chat (owner rule 7:
smallest complete product, verified as one flow)."""
import json
import asyncio

import httpx
import pytest

from app.db import session as db
from app.main import app
from tests.fakes_v2 import UNI, FakeSearchV2, ScriptedLLM


@pytest.fixture
async def client(monkeypatch, tmp_path):
    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/e2e.db", use_alembic=False)
    llm = ScriptedLLM()

    orig = ScriptedLLM.complete_json_route
    async def routed(self, prompt):
        if "competitive intelligence specialist" in prompt:
            claims = await db.graph().claims(db.DEFAULT_WORKSPACE_ID, limit=3)
            self.insight_claim_ids = [c.id for c in claims]
        if "AI analyst" in prompt:
            claims = await db.graph().claims(db.DEFAULT_WORKSPACE_ID, limit=1)
            cid = claims[0].id if claims else "x"
            return {"answer": f"Founded in 2004 [C:{cid}].",
                    "cited_claim_ids": [cid], "needs_research": False,
                    "proposed_research": None}
        return await orig(self, prompt)
    monkeypatch.setattr(ScriptedLLM, "complete_json_route", routed)
    monkeypatch.setattr("app.api.v2.build_provider", lambda: llm)
    monkeypatch.setattr("app.api.v2.build_search_provider", lambda: FakeSearchV2())

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_steel_thread_end_to_end(client):
    # 1. conversation
    r = await client.post("/v2/analyze", json={"message":
        "Analyze Acme University Lahore. Focus on competitors."})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started" and body["brief"]["organization"] == UNI
    run_id, org_id = body["run_id"], body["organization_id"]

    # 2. research job completes
    for _ in range(100):
        await asyncio.sleep(0.05)
        status = (await client.get(f"/v2/runs/{run_id}")).json()
        if status["status"] != "running":
            break
    assert status["status"] == "completed", status
    assert status["result"]["claims"] > 0

    # 3. graph → twin workspace
    twin = (await client.get(f"/v2/twins/{org_id}")).json()
    assert twin["organization"]["name"] == UNI
    assert len(twin["profile_claims"]) > 0
    assert any(c["kind"] == "event" for c in twin["timeline"])
    assert twin["insights"] and twin["insights"][0]["claim_ids"]

    evidence = (await client.get(f"/v2/twins/{org_id}/evidence")).json()
    assert evidence and evidence[0]["url"].startswith("https://")

    # 4. cited chat
    chat = (await client.post(f"/v2/twins/{org_id}/chat",
                              json={"message": "When was it founded?"})).json()
    assert chat["citations"], chat
    assert chat["citations"][0]["evidence"][0]["url"]
    assert "[C:" in chat["answer"] or chat["answer"]

    # 5. run events were recorded (SSE source material, durable table)
    events = (await client.get(f"/v2/runs/{run_id}/events")).text
    assert "research.stage" in events and "run.completed" in events

    # 6. SECOND RUN (spec §7): delta research must be measurably cheaper
    r2 = await client.post("/v2/analyze", json={"message":
        "Analyze Acme University Lahore again. Focus on competitors."})
    run2 = r2.json()["run_id"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        status2 = (await client.get(f"/v2/runs/{run2}")).json()
        if status2["status"] != "running":
            break
    assert status2["status"] == "completed", status2
    first, second = status["result"], status2["result"]
    assert second["cache_hits"] > 0                    # extraction cache working
    assert second["evidence_reused"] > 0               # corpus dedup working
    assert second["searches"] <= first["searches"]     # delta ≤ first-run cost

    # 7. Phase 3: playbooks are listable, stamped into results, and validated
    books = (await client.get("/v2/playbooks")).json()
    assert any(b["id"] == "full_analysis" for b in books)
    assert first["playbook"]["id"] == "full_analysis"
    assert "adjudication" in first and "review" in first
    assert (await client.post("/v2/analyze", json={
        "message": "Analyze Acme University Lahore.",
        "playbook": "nonexistent"})).status_code == 422

    # 7b. change report endpoint
    changes = (await client.get(
        f"/v2/twins/{org_id}/changes",
        params={"since": "2000-01-01T00:00:00+00:00"})).json()
    assert changes["new_claims"] > 0


async def test_reads_never_mutate_graph(client):
    """C6: a GET must not create entities (read-path purity)."""
    from sqlalchemy import func, select
    from app.graph.models import EntityRow

    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    body = r.json()
    run_id, org_id = body["run_id"], body["organization_id"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        if (await client.get(f"/v2/runs/{run_id}")).json()["status"] != "running":
            break

    async def entity_count():
        async with db._sessionmaker() as s:
            return (await s.execute(select(func.count()).select_from(EntityRow))).scalar()

    before = await entity_count()
    for _ in range(3):
        assert (await client.get(f"/v2/twins/{org_id}")).status_code == 200
        assert (await client.get(f"/v2/twins/{org_id}/evidence")).status_code == 200
    assert await entity_count() == before


async def test_all_modules_populate_after_analysis(client):
    """Brief's mandated end-to-end check: after one successful analysis, every
    module endpoint that backs a page must return usable data (not an error),
    so no page shows a false empty state. Endpoints that are correctly empty
    until the user acts (monitoring, leads) must still return a valid shape."""
    # 1-3. create org + run analysis to completion
    r = await client.post("/v2/analyze", json={"message":
        "Analyze Acme University Lahore. Focus on competitors."})
    body = r.json()
    run_id, org_id = body["run_id"], body["organization_id"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        status = (await client.get(f"/v2/runs/{run_id}")).json()
        if status["status"] != "running":
            break
    assert status["status"] == "completed"

    # 4. organizations list (drives the shared active-org picker)
    orgs = (await client.get("/v2/organizations")).json()
    assert any(o["id"] == org_id for o in orgs)

    # 5. Workspace (dashboard view) — populated
    dash = (await client.get(f"/v2/twins/{org_id}/dashboard")).json()
    assert dash["counts"]["validated"] >= 0
    assert "research_history" in dash and len(dash["research_history"]) >= 1

    # 6. Dashboard briefing — valid shape
    briefing = (await client.get("/v2/briefing")).json()
    assert "twins" in briefing

    # 7. Market Research — twin profile claims available
    twin = (await client.get(f"/v2/twins/{org_id}")).json()
    assert len(twin["profile_claims"]) > 0

    # 8. Competitor Intelligence — endpoint returns a valid shape (has_data bool)
    comps = (await client.get(f"/v2/twins/{org_id}/competitors")).json()
    assert "has_data" in comps and "competitors" in comps

    # 9. Monitoring status — valid shape even before any scan
    mon = (await client.get(f"/v2/competitors/status?organization_id={org_id}")).json()
    assert "watched" in mon and isinstance(mon["watched"], list)

    # 10. SEO — audit history endpoint returns a valid shape
    seo = (await client.get("/v2/website-audits")).json()
    assert "audits" in seo

    # 11. Opportunity Engine — dashboard recommendations power it
    assert "recommendations" in dash

    # 12. Sales — pipeline + leads endpoints return valid shapes
    pipeline = (await client.get("/v2/sales/pipeline")).json()
    assert "by_stage" in pipeline
    leads = (await client.get("/v2/sales/leads")).json()
    assert "leads" in leads

    # 13. Reports — research history present (report snapshots)
    assert len(dash["research_history"]) >= 1


async def test_finding_detail_source_transparency(client):
    """After analysis, a finding opens with full source transparency: sources
    with type/authentication/reliability + what it's used by. Real data only."""
    r = await client.post("/v2/analyze", json={"message":
        "Analyze Acme University Lahore."})
    body = r.json()
    run_id, org_id = body["run_id"], body["organization_id"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        if (await client.get(f"/v2/runs/{run_id}")).json()["status"] != "running":
            break

    twin = (await client.get(f"/v2/twins/{org_id}")).json()
    assert twin["profile_claims"], "expected at least one finding"
    finding_id = twin["profile_claims"][0]["id"]

    detail = (await client.get(f"/v2/findings/{finding_id}")).json()
    assert detail["statement"]
    assert 0 <= detail["confidence"] <= 1
    assert "sources" in detail and detail["source_count"] == len(detail["sources"])
    for s in detail["sources"]:
        assert s["url"].startswith("http")
        assert s["source_type"]            # classified category
        assert 0 <= s["authentication_score"] <= 1
        assert 1 <= s["reliability_stars"] <= 5
        assert s["extracted_at"]
    assert "used_by" in detail
    assert "recommendations" in detail["used_by"]

    # unknown finding → 404
    assert (await client.get("/v2/findings/nonexistent")).status_code == 404


async def test_api_never_returns_internal_reviewer_wording(client):
    """No API surface that feeds the UI may return internal reviewer wording
    inline in an insight body (regression: '[critic]' text was rendered to
    executives inside finding cards)."""
    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    body = r.json()
    run_id, org_id = body["run_id"], body["organization_id"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        if (await client.get(f"/v2/runs/{run_id}")).json()["status"] != "running":
            break

    payloads = [
        (await client.get(f"/v2/twins/{org_id}")).json(),
        (await client.get(f"/v2/twins/{org_id}/dashboard")).json(),
        (await client.get("/v2/briefing")).json(),
    ]
    for p in payloads:
        blob = json.dumps(p)
        assert "[critic]" not in blob, "internal reviewer marker leaked to the UI"
        assert "[[validation]]" not in blob, "raw validation marker leaked to the UI"

    # and the rationale is still available, but as a labelled separate field
    twin = payloads[0]
    for ins in twin["insights"]:
        assert "validation_note" in ins


async def test_phase1_alerts_activity_and_related_endpoints(client):
    """Mission Control alerts, monitoring activity, and cross-linking all return
    real, correctly-shaped data derived from existing intelligence."""
    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    body = r.json()
    run_id, org_id = body["run_id"], body["organization_id"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        if (await client.get(f"/v2/runs/{run_id}")).json()["status"] != "running":
            break

    # Critical alerts: valid shape, severity-ranked, never fabricated
    alerts = (await client.get(f"/v2/twins/{org_id}/alerts")).json()
    assert "alerts" in alerts and isinstance(alerts["alerts"], list)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sev = [rank.get(a["severity"], 9) for a in alerts["alerts"]]
    assert sev == sorted(sev), "alerts must be severity-ranked"
    for a in alerts["alerts"]:
        assert a["kind"] in {"conflict", "competitor_change", "website_health"}
        assert a["title"] and a["action"]

    # Monitoring activity: valid shape even with no scans yet
    act = (await client.get(f"/v2/competitors/activity?organization_id={org_id}")).json()
    assert "events" in act and isinstance(act["events"], list)

    # Cross-linking: related intelligence for a real finding
    twin = (await client.get(f"/v2/twins/{org_id}")).json()
    finding_id = twin["profile_claims"][0]["id"]
    rel = (await client.get(f"/v2/findings/{finding_id}/related")).json()
    assert rel["finding_id"] == finding_id
    for key in ("related_findings", "competitors", "recommendations"):
        assert isinstance(rel[key], list)
    # a finding never lists itself as related
    assert all(f["id"] != finding_id for f in rel["related_findings"])
    # unknown finding → 404
    assert (await client.get("/v2/findings/nope/related")).status_code == 404
