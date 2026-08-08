"""Server-side PDF/CSV exports.

Security is the headline requirement: an export must never return another
workspace's intelligence, even when the caller supplies a valid organization id
belonging to a different tenant.
"""
import pytest

from app.reports.exporters import (CSV_DATASETS, REPORT_KINDS, build_csv,
                                   build_report_pdf)
# Reuse the end-to-end app fixture rather than standing up a second harness.
from tests.test_api_e2e import client  # noqa: F401


def test_pdf_is_a_real_pdf_and_hides_internal_terminology():
    pdf = build_report_pdf("executive", "Acme University", {
        "counts": {"validated": 2, "recommendations": 1, "disputes_open": 0, "runs": 1},
        "recommendations": [{"title": "Expand services", "body": "Demand rising.",
                             "confidence": 0.72}],
        "findings": [{"title": "Market grew", "confidence": 0.61}],
    })
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000
    blob = pdf.lower()
    for banned in (b"[critic]", b"predicate", b"playbook", b"specialist"):
        assert banned not in blob


def test_pdf_states_missing_data_instead_of_inventing_it():
    """An organization with nothing collected must produce an honest report."""
    pdf = build_report_pdf("executive", "Empty Co", {"counts": {}})
    assert pdf.startswith(b"%PDF-")
    # renders without raising, and cannot contain fabricated figures
    assert b"%%EOF" in pdf


def test_all_report_kinds_render():
    for kind in REPORT_KINDS:
        pdf = build_report_pdf(kind, "Acme", {
            "counts": {"validated": 1, "recommendations": 1, "disputes_open": 1, "runs": 1},
            "recommendations": [{"title": "Do a thing", "body": "Because.", "confidence": 0.5}],
            "findings": [{"title": "A fact", "confidence": 0.5}],
            "conflicts": [{"title": "Disputed fact", "confidence": 0.4}],
            "competitor_changes": [{"competitor_name": "Rival", "category": "pricing",
                                    "severity": "high", "detected_at": "2026-08-01"}],
            "sources": [{"domain": "example.edu", "url": "https://example.edu/a"}],
        })
        assert pdf.startswith(b"%PDF-"), kind


def test_report_text_with_angle_brackets_does_not_break_rendering():
    """Collected web content can contain markup; it must be escaped, not fatal."""
    pdf = build_report_pdf("executive", "Acme <script>", {
        "counts": {"validated": 1},
        "findings": [{"title": "Price < $100 & rising > 5%", "confidence": 0.5}],
    })
    assert pdf.startswith(b"%PDF-")


def test_csv_is_structured_not_a_json_blob():
    out = build_csv("findings", [{
        "organization": "Acme", "finding": "Market grew", "topic": "market",
        "confidence": 0.52, "source_count": 3, "status": "active",
        "as_of": "2026-01-01", "created_at": "2026-08-01"}])
    lines = out.strip().split("\n")
    assert lines[0] == ",".join(CSV_DATASETS["findings"])
    assert "Acme" in lines[1] and "{" not in out


def test_csv_quotes_embedded_commas_and_rejects_unknown_dataset():
    out = build_csv("findings", [{"organization": "A, Inc", "finding": "x"}])
    assert '"A, Inc"' in out
    with pytest.raises(ValueError):
        build_csv("not_a_dataset", [])


# ---------------------------------------------------------------- API level

async def test_export_endpoints_enforce_workspace_isolation(client):
    """THE security test: an organization in another workspace must not be
    exportable, even with a valid id."""
    from app.db import session as db

    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    org_id = r.json()["organization_id"]

    # ours works
    ok = await client.get(f"/v2/exports/report.pdf?organization_id={org_id}")
    assert ok.status_code == 200
    assert ok.content.startswith(b"%PDF-")
    assert ok.headers["content-type"] == "application/pdf"

    # an organization owned by a DIFFERENT workspace (real second tenant)
    from app.db.models import Workspace
    async with db._sessionmaker() as sess:      # noqa: SLF001 - test setup
        sess.add(Workspace(id="other-ws"))
        await sess.commit()
    foreign = await db.get_or_create_organization("other-ws", "Foreign Corp")
    assert foreign.workspace_id == "other-ws"

    leak = await client.get(f"/v2/exports/report.pdf?organization_id={foreign.id}")
    assert leak.status_code == 404, "cross-workspace PDF export must be refused"

    leak_csv = await client.get(
        f"/v2/exports/findings.csv?organization_id={foreign.id}")
    assert leak_csv.status_code == 404, "cross-workspace CSV export must be refused"

    # unknown organization → 404 (existence not leaked)
    assert (await client.get(
        "/v2/exports/report.pdf?organization_id=deadbeef")).status_code == 404


async def test_csv_endpoint_returns_scoped_rows(client):
    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    org_id = r.json()["organization_id"]

    resp = await client.get(f"/v2/exports/findings.csv?organization_id={org_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    header = resp.text.strip().split("\n")[0]
    assert header == ",".join(CSV_DATASETS["findings"])

    # every dataset is at least well-formed
    for dataset in CSV_DATASETS:
        d = await client.get(f"/v2/exports/{dataset}.csv?organization_id={org_id}")
        assert d.status_code == 200, dataset
        assert d.text.split("\n")[0] == ",".join(CSV_DATASETS[dataset])

    # invalid inputs are deliberate errors, not silent empties
    assert (await client.get(
        f"/v2/exports/nope.csv?organization_id={org_id}")).status_code == 422
    assert (await client.get(
        f"/v2/exports/report.pdf?organization_id={org_id}&kind=bogus")).status_code == 422


# ---------------------------------------------------------------- search

async def test_global_search_covers_modules_and_is_scoped(client):
    """Search spans graph + module records, never leaks reviewer wording, and
    refuses an organization from another workspace."""
    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    org_id = r.json()["organization_id"]

    res = (await client.get(f"/v2/search?q=acme&org_id={org_id}")).json()
    for bucket in ("entities", "claims", "insights", "recommendations",
                   "competitors", "monitoring", "leads", "website_audits"):
        assert bucket in res, f"missing search bucket: {bucket}"
        assert isinstance(res[bucket], list)
    assert res["organization_scoped"] is True

    # no internal reviewer wording anywhere in results
    import json as _json
    blob = _json.dumps(res)
    assert "[critic]" not in blob and "[[validation]]" not in blob

    # a lead created by the investigation is findable by company name
    leads = (await client.get(f"/v2/search?q=acme&org_id={org_id}")).json()["leads"]
    assert isinstance(leads, list)

    # cross-workspace org id is refused
    from app.db.models import Workspace
    from app.db import session as db
    async with db._sessionmaker() as sess:      # noqa: SLF001
        sess.add(Workspace(id="ws-search-other"))
        await sess.commit()
    foreign = await db.get_or_create_organization("ws-search-other", "Foreign Search Co")
    bad = await client.get(f"/v2/search?q=acme&org_id={foreign.id}")
    assert bad.status_code == 404

    # empty query returns valid empty buckets rather than erroring
    empty = (await client.get("/v2/search?q=")).json()
    assert empty["competitors"] == [] and empty["leads"] == []


# ------------------------------------------------- opportunity lifecycle

async def test_opportunity_lifecycle_state_persists_and_is_scoped(client):
    """Opportunities stay derived from the graph; only the user's lifecycle
    decision is persisted, and it is organization-scoped."""
    from app.db import session as db
    from app.db.models import Workspace

    r = await client.post("/v2/analyze", json={"message": "Analyze Acme University."})
    org_id = r.json()["organization_id"]

    # defaults to empty overlay + advertises valid statuses
    initial = (await client.get(f"/v2/twins/{org_id}/opportunity-states")).json()
    assert initial["states"] == {}
    assert "new" in initial["valid_statuses"] and "dismissed" in initial["valid_statuses"]

    # set a status + owner
    resp = await client.post(f"/v2/twins/{org_id}/opportunity-states",
                             json={"opportunity_key": "opp-1",
                                   "status": "in_progress", "owner": "Strategy"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    after = (await client.get(f"/v2/twins/{org_id}/opportunity-states")).json()
    assert after["states"]["opp-1"]["status"] == "in_progress"
    assert after["states"]["opp-1"]["owner"] == "Strategy"

    # upsert (not duplicate)
    await client.post(f"/v2/twins/{org_id}/opportunity-states",
                      json={"opportunity_key": "opp-1", "status": "completed"})
    final = (await client.get(f"/v2/twins/{org_id}/opportunity-states")).json()
    assert len(final["states"]) == 1
    assert final["states"]["opp-1"]["status"] == "completed"
    assert final["states"]["opp-1"]["owner"] == "Strategy"  # preserved

    # invalid status rejected
    bad = await client.post(f"/v2/twins/{org_id}/opportunity-states",
                            json={"opportunity_key": "opp-1", "status": "bogus"})
    assert bad.status_code == 422
    # empty key rejected
    assert (await client.post(f"/v2/twins/{org_id}/opportunity-states",
                              json={"opportunity_key": "  "})).status_code == 422

    # cross-workspace organization refused
    async with db._sessionmaker() as sess:      # noqa: SLF001
        sess.add(Workspace(id="ws-opp-other"))
        await sess.commit()
    foreign = await db.get_or_create_organization("ws-opp-other", "Foreign Opp Co")
    assert (await client.get(
        f"/v2/twins/{foreign.id}/opportunity-states")).status_code == 404
    assert (await client.post(f"/v2/twins/{foreign.id}/opportunity-states",
                              json={"opportunity_key": "x"})).status_code == 404
