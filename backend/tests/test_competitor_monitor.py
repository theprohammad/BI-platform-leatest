"""Crayon-class competitor monitoring — change detection is real and derived
from measured signals. Pure diff logic tested exhaustively; full API flow
(monitor→timeline→alerts→ack→report) tested end-to-end. No fabrication."""
import httpx
import pytest

from app.analyzers.competitor_monitor import (
    build_snapshot, content_hash, diff_snapshots, extract_signals)


@pytest.fixture
async def client(tmp_path):
    from app.db import session as db
    from app.main import app
    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/crayon.db", use_alembic=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def test_extract_signals_finds_prices_and_plans():
    analysis = {"title": "Acme Pro & Enterprise", "meta_description": "Plans from $49/mo",
                "h1": ["Enterprise ready"], "technologies": ["React"], "word_count": 300}
    sig = extract_signals(analysis)
    assert any("49" in p for p in sig["prices"])
    assert "pro" in sig["plans"] and "enterprise" in sig["plans"]
    assert sig["technologies"] == ["React"]


def test_first_snapshot_has_no_changes():
    a = {"title": "X", "meta_description": "y", "h1": ["z"], "technologies": [], "word_count": 100}
    snap = build_snapshot(a, None)
    assert snap.is_first is True and snap.changes == []


def test_diff_detects_pricing_change():
    old = extract_signals({"title": "T", "meta_description": "From $49/mo", "h1": [], "technologies": [], "word_count": 200})
    new = extract_signals({"title": "T", "meta_description": "From $79/mo", "h1": [], "technologies": [], "word_count": 200})
    changes = diff_snapshots(old, new)
    assert any(c.category == "pricing" for c in changes)


def test_diff_detects_free_tier_removal_as_high_severity():
    old = extract_signals({"title": "Free plan available", "meta_description": "", "h1": ["Free forever"], "technologies": [], "word_count": 200})
    new = extract_signals({"title": "Enterprise plans", "meta_description": "", "h1": ["Enterprise ready"], "technologies": [], "word_count": 200})
    changes = diff_snapshots(old, new)
    plan_changes = [c for c in changes if "plan" in c.summary.lower()]
    assert plan_changes and plan_changes[0].severity == "high"


def test_diff_detects_tech_adoption():
    old = extract_signals({"title": "T", "meta_description": "d", "h1": [], "technologies": ["React"], "word_count": 200})
    new = extract_signals({"title": "T", "meta_description": "d", "h1": [], "technologies": ["React", "Stripe"], "word_count": 200})
    changes = diff_snapshots(old, new)
    tech = [c for c in changes if c.category == "tech"]
    assert tech and "Stripe" in tech[0].after


def test_no_changes_when_identical():
    a = {"title": "Same", "meta_description": "same", "h1": ["h"], "technologies": ["React"], "word_count": 500}
    sig = extract_signals(a)
    assert diff_snapshots(sig, sig) == []
    assert content_hash(sig) == content_hash(sig)


async def test_full_crayon_flow(client, monkeypatch):
    """monitor (baseline) → monitor (change) → timeline → alerts → ack → report."""
    from app.db import session as db
    from app.analyzers import website_intel

    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Acme Corp")

    # two different "crawls" of the same competitor URL
    PAGE_V1 = ("<html lang=en><head><title>Beta — Free CRM</title>"
               "<meta name=description content='The free CRM for teams'>"
               "</head><body><h1>Free CRM</h1>" + ("w " * 300) + "</body></html>")
    PAGE_V2 = ("<html lang=en><head><title>Beta — Enterprise CRM</title>"
               "<meta name=description content='The enterprise CRM for teams, from $99/mo'>"
               "<script src='https://js.stripe.com/v3/'></script>"
               "</head><body><h1>Enterprise CRM</h1>" + ("w " * 700) + "</body></html>")

    pages = {"v": PAGE_V1}

    class FakeResp:
        status_code = 200; url = "https://beta.com"
        headers = {}
        @property
        def text(self): return pages["v"]
    class FakeClient:
        def __init__(self,*a,**k): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): return False
        async def get(self,url): return FakeResp()
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    # 1) baseline
    r1 = (await client.post("/v2/competitors/monitor", json={
        "organization_id": org.id, "competitor_name": "Beta", "url": "https://beta.com"})).json()
    assert r1["ok"] is True and r1["is_first"] is True and r1["changes"] == []

    # 2) page changes → real changes detected
    pages["v"] = PAGE_V2
    r2 = (await client.post("/v2/competitors/monitor", json={
        "organization_id": org.id, "competitor_name": "Beta", "url": "https://beta.com"})).json()
    assert r2["ok"] is True and r2["is_first"] is False
    cats = {c["category"] for c in r2["changes"]}
    assert "messaging" in cats and "pricing" in cats and "tech" in cats

    # 3) timeline
    tl = (await client.get(f"/v2/competitors/timeline?organization_id={org.id}")).json()
    assert tl["count"] == len(r2["changes"])

    # 4) alerts (unacknowledged, severity-ranked)
    al = (await client.get(f"/v2/competitors/alerts?organization_id={org.id}")).json()
    assert al["count"] == tl["count"]
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ranks = [sev_rank[a["severity"]] for a in al["alerts"]]
    assert ranks == sorted(ranks)

    # 5) acknowledge one → drops from alerts
    ack_id = al["alerts"][0]["id"]
    assert (await client.post(f"/v2/competitors/changes/{ack_id}/acknowledge")).json()["ok"]
    al2 = (await client.get(f"/v2/competitors/alerts?organization_id={org.id}")).json()
    assert al2["count"] == al["count"] - 1

    # 6) report
    rep = (await client.get(f"/v2/competitors/report?organization_id={org.id}")).json()
    assert rep["has_data"] is True
    assert rep["total_changes"] == tl["count"]
    assert "pricing" in rep["by_category"]
    assert rep["most_active"][0]["competitor"] == "Beta"


async def test_monitor_honest_on_fetch_failure(client, monkeypatch):
    from app.db import session as db
    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Acme")
    class BoomClient:
        def __init__(self,*a,**k): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): return False
        async def get(self,url): raise httpx.ConnectError("unreachable")
    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    r = (await client.post("/v2/competitors/monitor", json={
        "organization_id": org.id, "competitor_name": "X", "url": "https://x.invalid"})).json()
    assert r["ok"] is False and r["changes"] == []


async def test_monitoring_status_reports_baseline_and_changes(client, monkeypatch):
    """The status endpoint distinguishes baseline (1 snapshot) from
    changes_detected, so the UI never shows a bare empty state."""
    from app.db import session as db
    import httpx as _httpx

    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Acme Status")

    pages = {"v": "<html lang=en><head><title>Beta Free</title>"
                  "<meta name=description content='free plan'></head>"
                  "<body><h1>Free</h1>" + ("w " * 200) + "</body></html>"}

    class FakeResp:
        status_code = 200; url = "https://status-test.com"; headers = {}
        @property
        def text(self): return pages["v"]
    class FakeClient:
        def __init__(self,*a,**k): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): return False
        async def get(self,url): return FakeResp()
    monkeypatch.setattr(_httpx, "AsyncClient", FakeClient)

    # first scan → baseline
    await client.post("/v2/competitors/monitor", json={
        "organization_id": org.id, "competitor_name": "Beta",
        "url": "https://status-test.com"})
    st = (await client.get(f"/v2/competitors/status?organization_id={org.id}")).json()
    assert st["watched_count"] == 1
    assert st["watched"][0]["status"] == "baseline"
    assert st["watched"][0]["snapshot_count"] == 1

    # second scan with a real change → changes_detected
    pages["v"] = ("<html lang=en><head><title>Beta Enterprise</title>"
                  "<meta name=description content='enterprise plan from $99/mo'></head>"
                  "<body><h1>Enterprise</h1>" + ("w " * 600) + "</body></html>")
    await client.post("/v2/competitors/monitor", json={
        "organization_id": org.id, "competitor_name": "Beta",
        "url": "https://status-test.com"})
    st2 = (await client.get(f"/v2/competitors/status?organization_id={org.id}")).json()
    assert st2["watched"][0]["status"] == "changes_detected"
    assert st2["watched"][0]["snapshot_count"] == 2
    assert st2["watched"][0]["change_count"] >= 1
