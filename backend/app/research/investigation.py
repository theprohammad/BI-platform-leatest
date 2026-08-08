"""Cross-module enrichment for a complete investigation.

The research loop builds the intelligence picture, but three product surfaces are
populated by their own collectors: Website Intelligence (audits), Monitoring
(page snapshots/baselines) and Sales (CRM/lead profiles). Historically a user had
to trigger those manually, so right after "Executive Intelligence" finished the
Website, Monitoring and Sales pages still looked empty.

This module runs those collectors once, automatically, for playbooks that declare
`full_investigation`. Design rules:

* **Additive** — reuses the existing collectors and store functions; no new
  tables, no API changes, no changes to the research loop itself.
* **Best-effort** — every step is isolated. A failure (no website, no network,
  no competitors found) is *recorded honestly* and never aborts the run or
  fabricates data.
* **Idempotent-ish** — monitoring baselines dedupe on URL by design, and audits
  are timestamped snapshots, so re-running is safe.
"""
from __future__ import annotations

from app.core.logging import get_logger

log = get_logger(__name__)

# How many discovered competitors to place under monitoring automatically.
MAX_AUTO_WATCH = 3


def _normalize_url(raw: str | None) -> str | None:
    """Return a fetchable http(s) URL, or None if there's nothing usable."""
    if not raw:
        return None
    url = raw.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


async def run_full_investigation(
    *,
    workspace_id: str,
    organization_id: str,
    organization_name: str,
    website: str | None,
    root_entity_id: str,
    db,
    graph,
) -> dict:
    """Populate Website Intelligence, Monitoring and Sales for an organization.

    Returns a per-step report so the UI/run record can show exactly what was
    collected and what wasn't (and why) — never a silent partial success.
    """
    report: dict = {
        "website_audit": {"status": "skipped", "reason": "no website on record"},
        "monitoring": {"status": "skipped", "reason": "no website on record",
                       "watched": 0},
        "crm_profile": {"status": "skipped", "reason": "not attempted"},
    }

    site = _normalize_url(website)

    # ---- 1. Website Intelligence -------------------------------------------
    audit: dict | None = None
    if site:
        try:
            from app.analyzers.website_intel import audit_website

            audit = await audit_website(site)
            if audit.get("ok"):
                audit_id = await db.save_website_audit(
                    workspace_id, site, ok=True,
                    scores=audit.get("scores", {}),
                    analysis=audit.get("analysis", {}),
                    organization_id=organization_id)
                report["website_audit"] = {"status": "completed",
                                           "audit_id": audit_id,
                                           "scores": audit.get("scores", {})}
            else:
                # Honest failure: the page genuinely couldn't be fetched.
                report["website_audit"] = {
                    "status": "unavailable",
                    "reason": audit.get("error", "the site could not be reached")}
        except Exception as exc:  # noqa: BLE001 - never abort the investigation
            log.warning("auto website audit failed: %s", exc)
            report["website_audit"] = {"status": "unavailable", "reason": str(exc)}

    # ---- 2. Monitoring baselines -------------------------------------------
    # Watch the organization's own site plus any competitor websites already
    # discovered during research, so "What changed?" has something to compare.
    watch_targets: list[tuple[str, str]] = []
    if site:
        watch_targets.append((organization_name, site))

    try:
        edges = await graph.competitor_edges_for_org(
            workspace_id, root_entity_id, organization_name)
        for edge in edges[:MAX_AUTO_WATCH]:
            entity = await graph.get_entity(edge.target_entity_id)
            if entity is None:
                continue
            attrs = entity.attributes or {}
            rival_site = _normalize_url(
                attrs.get("website") or attrs.get("url") or attrs.get("domain"))
            if rival_site:
                watch_targets.append((entity.name, rival_site))
    except Exception as exc:  # noqa: BLE001
        log.warning("competitor watch discovery failed: %s", exc)

    if watch_targets:
        watched = 0
        failures: list[str] = []
        for name, url in watch_targets:
            try:
                snap_audit = audit if (url == site and audit) else None
                if snap_audit is None:
                    from app.analyzers.website_intel import audit_website
                    snap_audit = await audit_website(url)
                if not snap_audit.get("ok"):
                    failures.append(f"{name}: {snap_audit.get('error', 'unreachable')}")
                    continue

                from app.analyzers.competitor_monitor import build_snapshot

                prev = await db.latest_competitor_snapshot(workspace_id, url)
                snap = build_snapshot(snap_audit["analysis"],
                                      prev["signals"] if prev else None)
                await db.save_competitor_snapshot(
                    workspace_id, organization_id, competitor_name=name,
                    url=url, page_type="homepage", signals=snap.signals,
                    content_hash=snap.content_hash)
                watched += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("auto monitoring baseline failed for %s: %s", url, exc)
                failures.append(f"{name}: {exc}")

        if watched:
            report["monitoring"] = {"status": "baseline_created",
                                    "watched": watched,
                                    "failures": failures}
        else:
            report["monitoring"] = {
                "status": "unavailable", "watched": 0,
                "reason": "; ".join(failures) or "no reachable pages to watch"}

    # ---- 3. CRM / lead profile ---------------------------------------------
    # An analyzed organization should already exist in Sales; only *advanced*
    # enrichment should need a manual discovery run.
    try:
        existing = await db.find_lead_by_organization(workspace_id, organization_id)
        if existing:
            report["crm_profile"] = {"status": "existing", "lead_id": existing}
        else:
            from app.analyzers.lead_scoring import score_lead
            from app.analyzers.sales_intel import enrich_company

            domain = None
            if site:
                domain = site.split("//", 1)[-1].split("/", 1)[0]

            org_row = await db.get_organization(organization_id)
            industry = getattr(org_row, "industry", None)

            # Reuse the same real enrichment path the manual discovery uses, so
            # the auto-created profile is not a lesser second-class record.
            enrichment = await enrich_company(domain, industry=industry) if domain else {}
            enrichment.setdefault("source", "investigation")
            scored = score_lead(enrichment)

            lead_id = await db.create_lead(
                workspace_id,
                company_name=organization_name,
                domain=domain,
                industry=industry,
                location=None,
                employee_range=None,
                enrichment=enrichment,
                score=scored.score,
                score_band=scored.band,
                score_breakdown=scored.as_dict(),
                organization_id=organization_id,
                source="investigation")

            contacts = enrichment.get("contacts", []) if enrichment else []
            if contacts:
                await db.add_contacts(workspace_id, lead_id, contacts)

            report["crm_profile"] = {"status": "created", "lead_id": lead_id,
                                     "score": scored.score, "band": scored.band}
    except Exception as exc:  # noqa: BLE001
        log.warning("auto CRM profile failed: %s", exc)
        report["crm_profile"] = {"status": "unavailable", "reason": str(exc)}

    return report
