"""Executive Intelligence must be a COMPLETE investigation.

Regression: selecting the full-analysis playbook previously ran research only,
leaving Website Intelligence, Monitoring and Sales empty — the user had to run
each module manually. These tests pin the cross-module enrichment contract.
"""
import pytest

from app.playbooks.registry import get_playbook
from app.research.investigation import run_full_investigation, _normalize_url


def test_only_full_analysis_declares_full_investigation():
    assert get_playbook("full_analysis").full_investigation is True
    assert get_playbook("competitor_scan").full_investigation is False
    assert get_playbook("pricing_watch").full_investigation is False


def test_normalize_url_adds_scheme_and_rejects_empty():
    assert _normalize_url("acme.edu") == "https://acme.edu"
    assert _normalize_url("https://acme.edu") == "https://acme.edu"
    assert _normalize_url("  ") is None
    assert _normalize_url(None) is None


async def test_full_investigation_populates_all_modules(monkeypatch, tmp_path):
    """With a reachable site, one run creates a website audit, a monitoring
    baseline and a CRM profile — no manual follow-up needed."""
    from app.db import session as db

    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/inv.db", use_alembic=False)
    org = await db.get_or_create_organization(
        db.DEFAULT_WORKSPACE_ID, "Acme University", website="acme.edu",
        industry="Education")

    analysis = {"title": "Acme University", "description": "A university",
                "technologies": ["React"], "word_count": 900,
                "headings": {"h1": ["Acme"]}, "links": {"internal": 5, "external": 2}}
    fake_audit = {"ok": True, "scores": {"overall": 71, "seo": 70},
                  "analysis": analysis}

    async def fake_audit_website(url):
        return fake_audit
    monkeypatch.setattr("app.analyzers.website_intel.audit_website",
                        fake_audit_website)

    async def fake_enrich(domain, **kw):
        return {"domain": domain, "website": {"ok": True, "analysis": analysis},
                "contacts": []}
    monkeypatch.setattr("app.analyzers.sales_intel.enrich_company", fake_enrich)

    report = await run_full_investigation(
        workspace_id=db.DEFAULT_WORKSPACE_ID,
        organization_id=org.id,
        organization_name="Acme University",
        website="acme.edu",
        root_entity_id=org.root_entity_id or "root",
        db=db, graph=db.graph())

    # 1. Website Intelligence populated
    assert report["website_audit"]["status"] == "completed"
    audits = await db.list_website_audits(db.DEFAULT_WORKSPACE_ID)
    assert len(audits) >= 1

    # 2. Monitoring baseline created
    assert report["monitoring"]["status"] == "baseline_created"
    assert report["monitoring"]["watched"] >= 1
    status = await db.competitor_monitoring_status(db.DEFAULT_WORKSPACE_ID, org.id)
    assert status["watched_count"] >= 1
    assert status["watched"][0]["status"] == "baseline"

    # 3. CRM profile auto-created (no manual discovery required)
    assert report["crm_profile"]["status"] == "created"
    leads = await db.list_leads(db.DEFAULT_WORKSPACE_ID)
    assert len(leads) >= 1
    created_id = report["crm_profile"]["lead_id"]
    assert any(l["id"] == created_id for l in leads)
    # the auto-created profile is linked back to the analyzed organization
    assert await db.find_lead_by_organization(
        db.DEFAULT_WORKSPACE_ID, org.id) == created_id

    # re-running does not duplicate the company profile
    again = await run_full_investigation(
        workspace_id=db.DEFAULT_WORKSPACE_ID, organization_id=org.id,
        organization_name="Acme University", website="acme.edu",
        root_entity_id=org.root_entity_id or "root", db=db, graph=db.graph())
    assert again["crm_profile"]["status"] == "existing"


async def test_unreachable_site_reports_honestly_never_fabricates(monkeypatch, tmp_path):
    """No network → the report says so explicitly instead of inventing scores."""
    from app.db import session as db

    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/inv2.db", use_alembic=False)
    org = await db.get_or_create_organization(
        db.DEFAULT_WORKSPACE_ID, "Unreachable Co", website="nope.invalid")

    async def failing_audit(url):
        return {"ok": False, "error": "name resolution failed"}
    monkeypatch.setattr("app.analyzers.website_intel.audit_website", failing_audit)

    report = await run_full_investigation(
        workspace_id=db.DEFAULT_WORKSPACE_ID, organization_id=org.id,
        organization_name="Unreachable Co", website="nope.invalid",
        root_entity_id=org.root_entity_id or "root", db=db, graph=db.graph())

    assert report["website_audit"]["status"] == "unavailable"
    assert "name resolution failed" in report["website_audit"]["reason"]
    assert report["monitoring"]["status"] == "unavailable"
    assert report["monitoring"]["watched"] == 0
    # no fabricated audit persisted
    audits = await db.list_website_audits(db.DEFAULT_WORKSPACE_ID)
    assert all(a.get("ok") is not True for a in audits) or len(audits) == 0


async def test_missing_website_skips_cleanly(tmp_path):
    """An org with no website recorded skips web steps with a stated reason."""
    from app.db import session as db

    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/inv3.db", use_alembic=False)
    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "No Site Inc")

    report = await run_full_investigation(
        workspace_id=db.DEFAULT_WORKSPACE_ID, organization_id=org.id,
        organization_name="No Site Inc", website=None,
        root_entity_id=org.root_entity_id or "root", db=db, graph=db.graph())

    assert report["website_audit"]["status"] == "skipped"
    assert report["monitoring"]["status"] == "skipped"
    assert "reason" in report["website_audit"]


async def test_monitoring_activity_timeline_explains_what_happened(monkeypatch, tmp_path):
    """Monitoring must be able to prove it is working: the activity timeline
    distinguishes a baseline from later scans, and records detections."""
    from app.db import session as db

    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/mon.db", use_alembic=False)
    org = await db.get_or_create_organization(db.DEFAULT_WORKSPACE_ID, "Watcher Inc")

    analysis = {"title": "Rival", "description": "cheap plans",
                "technologies": ["React"], "word_count": 500,
                "headings": {"h1": ["Rival"]}, "links": {"internal": 3, "external": 1}}

    from app.analyzers.competitor_monitor import build_snapshot
    snap = build_snapshot(analysis, None)
    await db.save_competitor_snapshot(
        db.DEFAULT_WORKSPACE_ID, org.id, competitor_name="Rival",
        url="https://rival.test", page_type="homepage",
        signals=snap.signals, content_hash=snap.content_hash)

    events = await db.competitor_activity_timeline(db.DEFAULT_WORKSPACE_ID, org.id)
    assert len(events) == 1
    assert events[0]["kind"] == "baseline_created"
    assert "Baseline" in events[0]["detail"]

    # a second scan of the same page is a scan, not another baseline
    analysis2 = dict(analysis, description="premium plans from $99")
    snap2 = build_snapshot(analysis2, snap.signals)
    await db.save_competitor_snapshot(
        db.DEFAULT_WORKSPACE_ID, org.id, competitor_name="Rival",
        url="https://rival.test", page_type="homepage",
        signals=snap2.signals, content_hash=snap2.content_hash)

    events2 = await db.competitor_activity_timeline(db.DEFAULT_WORKSPACE_ID, org.id)
    kinds = [e["kind"] for e in events2]
    assert kinds.count("baseline_created") == 1
    assert "scan_completed" in kinds
    # newest first
    assert events2[0]["at"] >= events2[-1]["at"]
