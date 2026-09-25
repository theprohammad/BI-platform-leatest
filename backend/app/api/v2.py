"""v2 API — the steel-thread surface. Thin adapters over the Tool Layer and
the run orchestration; NO business logic lives here (owner rule 3/8)."""
import asyncio
import json
import time
import uuid
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.analyst import AnalystChat
from app.core.config import get_settings
from app.core.events import Event, bus
from app.core.ledger import CostLedger
from app.core.logging import get_logger
from app.core.versions import run_manifest
from app.db import session as db
from app.graph.ontology import EntityType
from app.graph.store import split_validation_note
from app.intake.intake_agent import IntakeAgent
from app.providers.llm.router import LLMRouter, build_provider
from app.providers.search.tavily_provider import build_search_provider
from app.research.loop import ResearchLoop
from app.runner.task_runner import runner
from app.tools.registry import Budget, ToolContext, registry  # noqa: F401 (registry import loads tools)


def _public_insight(insight) -> dict:
    """Serialize an insight for the UI. Splits the stored validation rationale
    out of the narrative body so internal reviewer wording is never shown inline;
    it is returned as `validation_note` for display under a business label."""
    d = insight.model_dump()
    body, note = split_validation_note(d.get("body", "") or "")
    d["body"] = body
    d["validation_note"] = note
    return d
import app.tools.graph_tools  # noqa: F401  register graph tools
import app.tools.web_tools    # noqa: F401  register web tools

log = get_logger("api.v2")
router = APIRouter(prefix="/v2")

WORKSPACE = db.DEFAULT_WORKSPACE_ID


class AnalyzeIn(BaseModel):
    message: str
    # continuation of a clarification exchange, optional:
    prior_message: str | None = None
    playbook: str | None = None       # Phase 3: named research program


class ChatIn(BaseModel):
    message: str


def _tool_ctx(run_id: str, organization_id: str | None = None,
              playbook_id: str | None = None) -> ToolContext:
    from app.playbooks.registry import get_playbook
    settings = get_settings()
    ledger = CostLedger()
    playbook = get_playbook(playbook_id)
    return ToolContext(
        workspace_id=WORKSPACE, run_id=run_id, graph=db.graph(),
        search=build_search_provider(),
        llm=LLMRouter(build_provider(), ledger=ledger, run_id=run_id),
        budget=Budget(max_searches=playbook.max_searches,
                      max_llm_calls=playbook.max_llm_calls,
                      deadline_epoch=time.time() + settings.run_wallclock_budget_seconds),
        organization_id=organization_id,
        ledger=ledger,
        playbook=playbook,
    )


@router.get("/playbooks")
async def playbooks():
    """Phase 3: available research programs."""
    from app.playbooks.registry import list_playbooks
    return list_playbooks()


@router.post("/analyze")
async def analyze(body: AnalyzeIn):
    """Conversational intake → either a clarifying question, or a started run."""
    if not db.enabled():
        raise HTTPException(503, "Persistence is required for v2 (set DATABASE_URL)")
    from app.playbooks.registry import get_playbook
    try:
        get_playbook(body.playbook)                    # 422 before any work
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    run_id = uuid.uuid4().hex[:12]
    ctx = _tool_ctx(run_id, playbook_id=body.playbook)

    message = f"{body.prior_message}\n{body.message}" if body.prior_message else body.message
    brief = await IntakeAgent().run(ctx.llm, message)

    if brief.needs_clarification:
        return {"status": "needs_clarification",
                "question": brief.clarifying_question or
                "Which organization would you like me to analyze?"}

    root = await registry.invoke(ctx, "graph.resolve_entity",
                                 name=brief.organization,
                                 type=EntityType.ORGANIZATION)
    org = await db.get_or_create_organization(WORKSPACE, brief.organization,
                                              website=brief.website,
                                              industry=brief.industry,
                                              root_entity_id=root.id)
    ctx.organization_id = org.id

    async def job():
        stats = await ResearchLoop().run(ctx, brief=brief.model_dump(),
                                         root_entity_id=root.id)
        # A "full investigation" playbook also populates Website Intelligence,
        # Monitoring and Sales, so the user never has to run those separately.
        # Best-effort: failures are recorded in the run record, never fatal.
        spec = get_playbook(body.playbook)
        if spec.full_investigation:
            try:
                from app.research.investigation import run_full_investigation
                stats["investigation"] = await run_full_investigation(
                    workspace_id=WORKSPACE,
                    organization_id=org.id,
                    organization_name=brief.organization,
                    website=brief.website or getattr(org, "website", None),
                    root_entity_id=root.id,
                    db=db, graph=db.graph())
            except Exception as exc:  # noqa: BLE001
                log.warning("full investigation enrichment failed: %s", exc)
                stats["investigation"] = {"status": "unavailable",
                                          "reason": str(exc)}
        await db.persist_v2_run(run_id, WORKSPACE, org.id, brief.model_dump(),
                                run_manifest(), ctx.ledger.summary(), stats)
        await bus.publish(Event("run.completed", run_id,
                                {"organization_id": org.id, **{k: v for k, v in stats.items() if k != "insights"}}))
        return stats

    runner.start(job, run_id=run_id)
    return {"status": "started", "run_id": run_id,
            "organization_id": org.id, "root_entity_id": root.id,
            "brief": brief.model_dump()}


@router.get("/runs/{run_id}")
async def run_status(run_id: str):
    job = runner.status(run_id)          # same-process cache
    if job is not None:
        return {"run_id": run_id, "status": job.status, "error": job.error,
                "result": job.result if job.status == "completed" else None}
    row = await db.get_job(run_id)       # S6: DB is the source of truth
    if row is None:
        raise HTTPException(404, "unknown run")
    return {"run_id": run_id, "status": row.status, "error": row.error,
            "result": row.result if row.status == "completed" else None}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str):
    """SSE: replay from the events TABLE (survives restarts — B3 fix), then
    live-follow the bus with a table-tail fallback; terminal state from the
    jobs table so streams always end."""
    async def stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def handler(event: Event):
            if event.run_id == run_id:
                await queue.put(event.as_dict())

        last_seq = 0
        for past in await db.events_for_run(run_id):
            last_seq = past["seq"]
            yield f"data: {json.dumps(past)}\n\n"
            if past["type"] in ("run.completed", "run.failed"):
                return
        bus.subscribe(handler)
        try:
            idle_cycles = 0
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5)
                    idle_cycles = 0
                    yield f"data: {json.dumps(event)}\n\n"
                    if event["type"] in ("run.completed", "run.failed"):
                        return
                except asyncio.TimeoutError:
                    idle_cycles += 1
                    # table tail (another process may be running the job)
                    for row in await db.events_for_run(run_id, after_seq=last_seq):
                        last_seq = row["seq"]
                        yield f"data: {json.dumps(row)}\n\n"
                        if row["type"] in ("run.completed", "run.failed"):
                            return
                    job = await db.get_job(run_id)
                    if job is not None and job.status in ("completed", "failed"):
                        yield f"data: {json.dumps({'type': f'run.{job.status}', 'run_id': run_id, 'payload': {}})}\n\n"
                        return
                    if idle_cycles >= 60:      # 5-min hard stop, never hangs
                        return
                    yield ": keepalive\n\n"
        finally:
            if handler in bus._subscribers:
                bus._subscribers.remove(handler)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/twins")
async def twins():
    return await db.list_organizations(WORKSPACE)


@router.get("/twins/{org_id}")
async def twin(org_id: str):
    org = await db.get_organization(org_id)
    if org is None:
        raise HTTPException(404, "unknown organization")
    if not org.root_entity_id:
        raise HTTPException(409, "twin has no root entity (re-run analysis)")
    ctx = _tool_ctx(f"view-{org_id[:8]}", org_id)
    root_id = org.root_entity_id            # C6: reads never resolve-by-name
    profile = await registry.invoke(ctx, "graph.claims",
                                    subject_entity_id=root_id, limit=100)
    timeline = await registry.invoke(ctx, "graph.timeline", subject_entity_id=root_id)
    insights = await registry.invoke(ctx, "graph.insights")
    coverage = await registry.invoke(ctx, "graph.coverage", subject_entity_id=root_id)
    return {
        "organization": {"id": org.id, "name": org.name, "website": org.website,
                         "industry": org.industry},
        "root_entity_id": root_id,
        "coverage": coverage,
        "profile_claims": [c.model_dump() for c in profile],
        "timeline": [c.model_dump() for c in timeline],
        "insights": [_public_insight(i) for i in insights],
    }


@router.get("/twins/{org_id}/evidence")
async def twin_evidence(org_id: str):
    org = await db.get_organization(org_id)
    if org is None:
        raise HTTPException(404, "unknown organization")
    if not org.root_entity_id:
        raise HTTPException(409, "twin has no root entity (re-run analysis)")
    ctx = _tool_ctx(f"view-{org_id[:8]}", org_id)
    claims = await registry.invoke(ctx, "graph.claims",
                                   subject_entity_id=org.root_entity_id, limit=300)
    ev_ids = list(dict.fromkeys(eid for c in claims for eid in c.evidence_ids))[:100]
    evidence = await registry.invoke(ctx, "graph.evidence", evidence_ids=ev_ids)
    return [{"id": e.id, "url": e.url, "domain": e.domain, "title": e.title,
             "published_date": e.published_date, "retrieved_at": e.retrieved_at,
             "quality_score": e.quality_score,
             "preview": e.content[:400]} for e in evidence]


@router.post("/twins/{org_id}/chat")
async def twin_chat(org_id: str, body: ChatIn):
    org = await db.get_organization(org_id)
    if org is None:
        raise HTTPException(404, "unknown organization")
    if not org.root_entity_id:
        raise HTTPException(409, "twin has no root entity (re-run analysis)")
    ctx = _tool_ctx(f"chat-{uuid.uuid4().hex[:8]}", org_id)
    answer = await AnalystChat().ask(ctx, organization=org.name,
                                     root_entity_id=org.root_entity_id,
                                     question=body.message)
    return answer.model_dump()


@router.post("/twins/{org_id}/refresh")
async def twin_refresh(org_id: str):
    """S8 Monitoring Stage A: delta run targeting stale/weak/disputed topics
    (quality coverage) + re-fetch of high-fan-in evidence URLs."""
    org = await db.get_organization(org_id)
    if org is None:
        raise HTTPException(404, "unknown organization")
    if not org.root_entity_id:
        raise HTTPException(409, "twin has no root entity (run an analysis first)")
    from datetime import datetime, timezone
    run_id = uuid.uuid4().hex[:12]
    ctx = _tool_ctx(run_id, org.id)
    since = datetime.now(timezone.utc).isoformat()

    async def job():
        from app.research.refresh import run_refresh
        stats = await run_refresh(ctx, organization=org.name,
                                  root_entity_id=org.root_entity_id,
                                  since_iso=since)
        await db.persist_v2_run(run_id, WORKSPACE, org.id,
                                {"mode": "refresh"}, run_manifest(),
                                ctx.ledger.summary(), stats)
        await bus.publish(Event("run.completed", run_id,
                                {"organization_id": org.id, "mode": "refresh"}))
        return stats

    runner.start(job, run_id=run_id)
    return {"status": "started", "run_id": run_id, "organization_id": org.id,
            "mode": "refresh"}


@router.get("/twins/{org_id}/changes")
async def twin_changes(org_id: str, since: str):
    """S7: change report — what the graph learned since a timestamp."""
    org = await db.get_organization(org_id)
    if org is None:
        raise HTTPException(404, "unknown organization")
    if not org.root_entity_id:
        raise HTTPException(409, "twin has no root entity")
    ctx = _tool_ctx(f"chg-{org_id[:8]}", org_id)
    from app.graph.diff import build_change_report
    return await build_change_report(ctx, org.root_entity_id, since)


# ======================================================================
# Intelligence Workspace — read-only product surface (frozen architecture).
# Thin adapters over the store's side-effect-free read helpers. No business
# logic; no new architectural concepts.
# ======================================================================

def _org_or_404(org):
    """Reject unknown organizations AND organizations owned by another
    workspace. A bare primary-key lookup is not sufficient: without the tenancy
    check, changing an id in a URL would expose another tenant's intelligence.
    Same 404 either way, so existence is not leaked."""
    if org is None or getattr(org, "workspace_id", None) != WORKSPACE:
        raise HTTPException(404, "unknown organization")
    return org


@router.get("/organizations")
async def organizations():
    """Twins the user can open."""
    return await db.list_organizations(WORKSPACE)


@router.get("/twins/{org_id}/dashboard")
async def twin_dashboard(org_id: str,
                         status: str | None = None,
                         playbook: str | None = None,
                         since: str | None = None):
    """Dashboard: insights, recommendations, disputes, research history, all
    with trust. Optional filters: debate status, playbook, since-date."""
    org = _org_or_404(await db.get_organization(org_id))
    graph = db.graph()
    insights = await graph.insights(WORKSPACE, org.id)

    def keep(i) -> bool:
        if status and i.debate_status != status:
            return False
        if since and (i.created_at or "")[:len(since)] < since:
            return False
        return True

    filtered = [i for i in insights if keep(i)]
    recommendations = [_public_insight(i) for i in filtered
                       if i.kind.value == "recommendation"]
    disputes = [_public_insight(i) for i in filtered if i.kind.value == "dispute"]
    validated = [_public_insight(i) for i in filtered
                 if i.kind.value in ("finding", "signal")
                 and i.debate_status == "validated"]
    other_insights = [_public_insight(i) for i in filtered
                      if i.kind.value in ("finding", "signal")
                      and i.debate_status != "validated"]
    runs = await db.list_runs(WORKSPACE, org.id)
    if playbook:
        runs = [r for r in runs if (r.get("playbook") or {}).get("id") == playbook]
    dispute_buckets = {"open": [], "deferred": [], "resolved": []}
    for d in disputes:
        bucket = ("resolved" if d["debate_status"] == "resolved"
                  else "deferred" if d["debate_status"] == "deferred"
                  else "open")
        dispute_buckets[bucket].append(d)
    return {"organization": {"id": org.id, "name": org.name,
                             "root_entity_id": org.root_entity_id},
            "validated_insights": validated,
            "other_insights": other_insights,
            "recommendations": recommendations,
            "disputes": dispute_buckets,
            "research_history": runs,
            "counts": {"validated": len(validated),
                       "recommendations": len(recommendations),
                       "disputes_open": len(dispute_buckets["open"]),
                       "disputes_deferred": len(dispute_buckets["deferred"]),
                       "disputes_resolved": len(dispute_buckets["resolved"]),
                       "runs": len(runs)}}


@router.get("/twins/{org_id}/recommendations")
async def twin_recommendations(org_id: str):
    org = _org_or_404(await db.get_organization(org_id))
    insights = await db.graph().insights(WORKSPACE, org.id, kind="recommendation")
    return [_public_insight(i) for i in insights]


@router.get("/twins/{org_id}/recommendations/{insight_id}/chain")
async def recommendation_chain(org_id: str, insight_id: str):
    """Full evidence chain: recommendation → insights → claims → evidence."""
    org = _org_or_404(await db.get_organization(org_id))
    chain = await db.graph().recommendation_chain(WORKSPACE, org.id, insight_id)
    if chain is None:
        raise HTTPException(404, "unknown recommendation")
    return chain


@router.get("/twins/{org_id}/disputes")
async def twin_disputes(org_id: str):
    org = _org_or_404(await db.get_organization(org_id))
    insights = await db.graph().insights(WORKSPACE, org.id, kind="dispute")
    return [_public_insight(i) for i in insights]


@router.get("/twins/{org_id}/disputes/{insight_id}")
async def dispute_detail(org_id: str, insight_id: str):
    """Conflicting-intelligence detail: both versions of the fact, their trust and
    sources, the validation review outcome, and current status. The reviewer
    rationale is returned as a separate field so it is never shown inline."""
    org = _org_or_404(await db.get_organization(org_id))
    detail = await db.graph().dispute_detail(WORKSPACE, org.id, insight_id)
    if detail is None:
        raise HTTPException(404, "unknown dispute")
    dispute = detail.get("dispute")
    if isinstance(dispute, dict):
        body, note = split_validation_note(dispute.get("body", "") or "")
        dispute["body"] = body
        dispute["validation_note"] = note
    return detail


@router.get("/briefing")
async def executive_briefing():
    """Workspace-level executive briefing aggregated across all twins.

    Additive read endpoint (Rule 2): composes existing per-twin dashboard data
    into a morning-brief shape. Everything is grounded in real graph data —
    no fabricated business-impact or revenue figures (Rule 4). The priority
    feed is derived from actual open disputes, fresh signals, and validated
    recommendations, each carrying its own trust so the UI can rank by
    confidence and surface evidence.
    """
    graph = db.graph()
    orgs = await db.list_organizations(WORKSPACE)
    twins: list[dict] = []
    totals = {"validated": 0, "recommendations": 0, "disputes_open": 0,
              "signals": 0, "runs": 0, "evidence": 0}
    priority: list[dict] = []
    discoveries: list[dict] = []

    for o in orgs:
        org = await db.get_organization(o["id"])
        if org is None:
            continue
        insights = await graph.insights(WORKSPACE, org.id)
        recs = [i for i in insights if i.kind.value == "recommendation"]
        disputes_open = [i for i in insights if i.kind.value == "dispute"
                         and i.debate_status not in ("resolved", "deferred")]
        signals = [i for i in insights if i.kind.value == "signal"]
        validated = [i for i in insights if i.kind.value in ("finding", "signal")
                     and i.debate_status == "validated"]
        runs = await db.list_runs(WORKSPACE, org.id)
        ev_count = sum(len(i.claim_ids) for i in insights)

        totals["validated"] += len(validated)
        totals["recommendations"] += len(recs)
        totals["disputes_open"] += len(disputes_open)
        totals["signals"] += len(signals)
        totals["runs"] += len(runs)
        totals["evidence"] += ev_count

        twins.append({
            "id": org.id, "name": org.name,
            "counts": {"validated": len(validated), "recommendations": len(recs),
                       "disputes_open": len(disputes_open), "signals": len(signals),
                       "runs": len(runs)},
            "last_run": runs[0]["created_at"] if runs else None,
        })

        # Priority feed — real items, each with severity derived from kind +
        # confidence. Disputes are attention items; signals are change items;
        # high-confidence recommendations are opportunities.
        for d in disputes_open:
            priority.append({
                "severity": "high", "kind": "dispute", "org_id": org.id,
                "org_name": org.name, "id": d.id, "title": d.title,
                "confidence": d.trust.confidence, "at": d.created_at,
                "evidence_count": len(d.claim_ids),
                "action": "Review conflicting evidence",
            })
        for s in signals:
            priority.append({
                "severity": "medium", "kind": "signal", "org_id": org.id,
                "org_name": org.name, "id": s.id, "title": s.title,
                "confidence": s.trust.confidence, "at": s.created_at,
                "evidence_count": len(s.claim_ids),
                "action": "Inspect change",
            })
        for r in sorted(recs, key=lambda x: -x.trust.confidence)[:3]:
            priority.append({
                "severity": "high" if r.trust.confidence >= 0.7 else "medium",
                "kind": "recommendation", "org_id": org.id, "org_name": org.name,
                "id": r.id, "title": r.title, "confidence": r.trust.confidence,
                "at": r.created_at, "evidence_count": len(r.claim_ids),
                "action": "Act on recommendation",
            })
        for i in sorted(insights, key=lambda x: x.created_at or "", reverse=True)[:5]:
            discoveries.append({
                "org_id": org.id, "org_name": org.name, "id": i.id,
                "kind": i.kind.value, "title": i.title,
                "confidence": i.trust.confidence, "at": i.created_at,
                "status": i.debate_status,
            })

    sev_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    priority.sort(key=lambda p: (sev_rank.get(p["severity"], 9),
                                 -(p["confidence"] or 0)))
    discoveries.sort(key=lambda d: d["at"] or "", reverse=True)

    return {
        "generated_at": _now_iso(),
        "twins": twins,
        "totals": totals,
        "priority_feed": priority[:12],
        "discoveries": discoveries[:20],
        "has_data": len(orgs) > 0,
    }


@router.get("/twins/{org_id}/competitors")
async def twin_competitors(org_id: str):
    """Competitor intelligence sourced entirely from the graph (Rule 2/5): the
    twin's `competitor_of` edges → competitor entities → their active claims →
    evidence. No fabricated funding/traffic/employee numbers — fields with no
    collected evidence are simply absent, and the UI renders 'Not yet collected'.
    Every competitor's profile is a real evidence chain."""
    org = _org_or_404(await db.get_organization(org_id))
    if not org.root_entity_id:
        return {"organization": {"id": org.id, "name": org.name},
                "competitors": [], "has_data": False}
    graph = db.graph()
    edges = await graph.competitor_edges_for_org(
        WORKSPACE, org.root_entity_id, org.name)
    competitors: list[dict] = []
    for edge in edges:
        target = await graph.get_entity(edge.target_entity_id)
        if target is None:
            continue
        claims = await graph.claims(WORKSPACE, subject_entity_id=target.id)
        # group claims by topic bucket; attach evidence count + confidence
        profile: dict[str, list[dict]] = {}
        evidence_ids: set[str] = set()
        for c in claims:
            profile.setdefault(c.topic, []).append({
                "id": c.id, "statement": c.statement, "predicate": c.predicate,
                "value": c.value, "confidence": c.trust.confidence,
                "evidence_count": len(c.evidence_ids), "as_of": c.as_of,
            })
            evidence_ids.update(c.evidence_ids)
        # a simple, evidence-derived confidence for the competitor as a whole
        avg_conf = (sum(c.trust.confidence for c in claims) / len(claims)
                    if claims else None)
        competitors.append({
            "id": target.id, "name": target.name,
            "aliases": list(target.aliases),
            "claim_count": len(claims),
            "evidence_count": len(evidence_ids),
            "confidence": round(avg_conf, 3) if avg_conf is not None else None,
            "profile": profile,           # keyed by topic: profile/pricing/market/...
            "edge_confidence": edge.trust.confidence if edge.trust else None,
        })
    competitors.sort(key=lambda c: -(c["claim_count"]))
    return {"organization": {"id": org.id, "name": org.name},
            "competitors": competitors,
            "has_data": len(competitors) > 0}


class MonitorIn(BaseModel):
    organization_id: str
    competitor_name: str
    url: str
    page_type: str = "homepage"


@router.post("/competitors/monitor")
async def competitor_monitor(body: MonitorIn):
    """Crawl a competitor page, snapshot its signals, and diff against the last
    snapshot to detect REAL changes (Crayon-class). Persists the snapshot and
    any changes. First run establishes a baseline (no changes). Never fabricates
    — if the page can't be fetched it says so honestly.
    """
    from app.analyzers.website_intel import audit_website
    from app.analyzers.competitor_monitor import build_snapshot

    audit = await audit_website(body.url)
    if not audit.get("ok"):
        return {"ok": False, "error": audit.get("error", "fetch failed"),
                "changes": [], "is_first": False}

    analysis = audit["analysis"]
    prev = await db.latest_competitor_snapshot(WORKSPACE, body.url)
    prev_signals = prev["signals"] if prev else None
    snap = build_snapshot(analysis, prev_signals)

    await db.save_competitor_snapshot(
        WORKSPACE, body.organization_id, competitor_name=body.competitor_name,
        url=body.url, page_type=body.page_type, signals=snap.signals,
        content_hash=snap.content_hash)

    change_dicts = [c.__dict__ for c in snap.changes]
    change_ids: list[str] = []
    if change_dicts:
        change_ids = await db.save_competitor_changes(
            WORKSPACE, body.organization_id,
            competitor_name=body.competitor_name, url=body.url, changes=change_dicts)

    return {"ok": True, "is_first": snap.is_first,
            "changes": change_dicts, "change_ids": change_ids,
            "signals": snap.signals}


@router.get("/competitors/timeline")
async def competitor_timeline(organization_id: str | None = None,
                              competitor_name: str | None = None):
    """The competitor change timeline — real detected changes, newest first."""
    changes = await db.list_competitor_changes(
        WORKSPACE, organization_id=organization_id, competitor_name=competitor_name)
    return {"changes": changes, "count": len(changes)}


@router.get("/competitors/alerts")
async def competitor_alerts(organization_id: str | None = None):
    """Unacknowledged changes, treated as alerts (severity-ranked)."""
    changes = await db.list_competitor_changes(
        WORKSPACE, organization_id=organization_id, unacknowledged_only=True)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    changes.sort(key=lambda c: rank.get(c["severity"], 9))
    return {"alerts": changes, "count": len(changes)}


@router.post("/competitors/changes/{change_id}/acknowledge")
async def competitor_ack(change_id: str):
    ok = await db.acknowledge_competitor_change(WORKSPACE, change_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Change not found")
    return {"ok": True}


@router.get("/competitors/status")
async def competitor_status(organization_id: str):
    """Per-URL monitoring status (snapshot counts, first/last scan, changes) so
    the UI can show 'baseline created / monitoring active / waiting for next
    comparison' instead of an empty state after the first scan."""
    return await db.competitor_monitoring_status(WORKSPACE, organization_id)


@router.get("/competitors/activity")
async def competitor_activity(organization_id: str, limit: int = 60):
    """Chronological monitoring activity (baselines, scans, detections) so users
    can see that monitoring is working even when nothing has changed."""
    return {"events": await db.competitor_activity_timeline(
        WORKSPACE, organization_id, limit=limit)}


@router.get("/twins/{org_id}/alerts")
async def twin_alerts(org_id: str, limit: int = 8):
    """Critical alerts for an organization — only genuinely important items,
    aggregated from intelligence we already hold: unresolved conflicting
    intelligence, unacknowledged high-severity competitor changes, and serious
    website health problems. Nothing is invented; if there is nothing important
    the list is empty and the UI says so explicitly."""
    org = _org_or_404(await db.get_organization(org_id))
    graph = db.graph()
    alerts: list[dict] = []

    # 1. Conflicting intelligence still open — sources disagree on a fact.
    try:
        insights = await graph.insights(WORKSPACE, org.id)
        for ins in insights:
            if ins.kind.value == "dispute" and ins.debate_status not in (
                    "resolved", "validated"):
                alerts.append({
                    "kind": "conflict",
                    "severity": "high",
                    "title": ins.title,
                    "detail": "Sources disagree on this fact — review before relying on it.",
                    "at": None,
                    "action": "Review conflicting intelligence",
                    "ref": {"type": "dispute", "id": ins.id},
                })
    except Exception:  # noqa: BLE001 - alerts must never break the workspace
        pass

    # 2. Unacknowledged competitor changes, severity-ranked.
    try:
        changes = await db.list_competitor_changes(
            WORKSPACE, organization_id=org.id, unacknowledged_only=True)
        for ch in changes:
            if ch.get("severity") in ("critical", "high"):
                alerts.append({
                    "kind": "competitor_change",
                    "severity": ch.get("severity", "high"),
                    "title": f"{ch.get('competitor_name')}: {ch.get('category')} changed",
                    "detail": ch.get("summary", ""),
                    "at": ch.get("created_at"),
                    "action": "Review competitor change",
                    "ref": {"type": "change", "id": ch.get("id")},
                })
    except Exception:  # noqa: BLE001
        pass

    # 3. Website health problems from the most recent audit.
    try:
        audits = await db.list_website_audits(WORKSPACE, organization_id=org.id)
        if audits:
            latest = audits[0]
            scores = latest.get("scores") or {}
            overall = scores.get("overall")
            if isinstance(overall, (int, float)) and overall < 60:
                alerts.append({
                    "kind": "website_health",
                    "severity": "critical" if overall < 40 else "high",
                    "title": f"Website health score is {int(overall)}/100",
                    "detail": "Technical issues are likely costing visibility and trust.",
                    "at": latest.get("created_at"),
                    "action": "Open Website Intelligence",
                    "ref": {"type": "audit", "id": latest.get("id")},
                })
    except Exception:  # noqa: BLE001
        pass

    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(key=lambda a: rank.get(a.get("severity", "low"), 9))
    return {"alerts": alerts[:limit], "count": len(alerts)}


@router.get("/competitors/report")
async def competitor_report(organization_id: str):
    """Executive competitor report: change counts by category + severity, most
    active competitors, and the recent timeline — all from real detected data."""
    changes = await db.list_competitor_changes(
        WORKSPACE, organization_id=organization_id, limit=500)
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_competitor: dict[str, int] = {}
    for c in changes:
        by_category[c["category"]] = by_category.get(c["category"], 0) + 1
        by_severity[c["severity"]] = by_severity.get(c["severity"], 0) + 1
        by_competitor[c["competitor_name"]] = by_competitor.get(c["competitor_name"], 0) + 1
    top = sorted(by_competitor.items(), key=lambda kv: -kv[1])[:5]
    return {
        "organization_id": organization_id,
        "total_changes": len(changes),
        "by_category": by_category,
        "by_severity": by_severity,
        "most_active": [{"competitor": k, "changes": v} for k, v in top],
        "recent": changes[:15],
        "has_data": len(changes) > 0,
    }


@router.get("/claims/{claim_id}/timeline")
async def claim_timeline(claim_id: str):
    """Claim lifecycle: created + every transition (superseded, resurrected,
    reactivated, adjudicated, deferred) with timestamps and reasons."""
    graph = db.graph()
    claims = await graph.get_claims([claim_id])
    if not claims:
        raise HTTPException(404, "unknown claim")
    claim = claims[0]
    transitions = await graph.transitions_for(claim_id)
    timeline = [{"to": "active", "from": None, "reason": "created",
                 "at": claim.created_at, "counterpart": None, "run_id": claim.run_id}]
    timeline.extend(transitions)
    return {"claim": claim.model_dump(), "timeline": timeline}


@router.get("/insights/{insight_id}")
async def insight_detail(insight_id: str):
    detail = await db.graph().insight_detail(insight_id, workspace_id=WORKSPACE)
    if detail is None:
        raise HTTPException(404, "unknown insight")
    return detail


def _classify_source(domain: str, source_type: str) -> dict:
    """Map a raw domain + internal source_type to executive-friendly source
    transparency: a business source category, an authentication score (how much
    we can trust the source's identity), and a plain label. No fabrication —
    derived deterministically from the domain."""
    d = (domain or "").lower().removeprefix("www.")
    category, auth = "Commercial", 0.6
    if d.endswith(".gov") or ".gov." in d or d.endswith(".mil"):
        category, auth = "Government", 0.98
    elif d.endswith(".edu") or ".edu." in d or d.endswith(".ac.uk"):
        category, auth = "Academic", 0.95
    elif any(d.endswith(s) or f".{s}" in d for s in (
            "reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "ft.com",
            "nytimes.com", "bbc.com", "bbc.co.uk", "economist.com", "forbes.com",
            "techcrunch.com", "theverge.com", "cnbc.com", "guardian.com")):
        category, auth = "News", 0.85
    elif any(s in d for s in ("github.com", "gitlab.com")):
        category, auth = "Official Repository", 0.9
    elif any(s in d for s in ("linkedin.com", "twitter.com", "x.com",
                              "facebook.com", "reddit.com", "medium.com")):
        category, auth = "Social / Community", 0.5
    elif source_type == "measurement":
        category, auth = "Direct Measurement", 0.92
    elif source_type == "user_attestation":
        category, auth = "User-Provided", 0.7
    elif source_type == "document":
        category, auth = "Official Document", 0.8
    return {"category": category, "authentication_score": auth}


def _reliability_stars(auth: float, corroboration: float) -> int:
    """1–5 star reliability from authentication + corroboration (both 0..1)."""
    score = 0.6 * auth + 0.4 * min(1.0, corroboration)
    return max(1, min(5, round(1 + score * 4)))


@router.get("/findings/{finding_id}")
async def finding_detail(finding_id: str):
    """Executive finding detail with full source transparency (source URL, type,
    authentication + reliability, extraction/verification dates), plus what the
    finding is *used by* (recommendations, other insights). Everything traces to
    real evidence — nothing fabricated. This backs the finding detail drawer."""
    graph = db.graph()
    claims = await graph.get_claims([finding_id])
    if not claims:
        raise HTTPException(404, "Finding not found")
    claim = claims[0]

    evidence = await graph.get_evidence(claim.evidence_ids)
    sources = []
    for e in evidence:
        cls = _classify_source(e.domain, e.source_type.value if hasattr(e.source_type, "value") else str(e.source_type))
        sources.append({
            "id": e.id,
            "url": e.url,
            "domain": e.domain,
            "title": e.title or e.domain,
            "source_type": cls["category"],
            "authentication_score": cls["authentication_score"],
            "reliability_stars": _reliability_stars(
                cls["authentication_score"], claim.trust.corroboration),
            "extracted_at": e.retrieved_at,
            "preview": e.content[:280],
        })

    # "Used by" — recommendations / insights that cite this finding
    citing = await graph.insights_citing_claim(finding_id)
    used_by = {"recommendations": [], "insights": []}
    for ins in citing:
        bucket = "recommendations" if ins.kind == "recommendation" else "insights"
        used_by[bucket].append({"id": ins.id, "title": ins.title,
                                "confidence": round(ins.trust.confidence, 2)})

    return {
        "id": claim.id,
        "statement": claim.statement,
        "topic": claim.topic,
        "confidence": round(claim.trust.confidence, 3),
        "corroboration": round(claim.trust.corroboration, 3),
        "source_quality": round(claim.trust.source_quality, 3),
        "freshness": round(claim.trust.freshness, 3),
        "status": claim.status,
        "as_of": claim.as_of,
        "created_at": claim.created_at,
        "sources": sources,
        "source_count": len(sources),
        "used_by": used_by,
    }


@router.get("/findings/{finding_id}/related")
async def finding_related(finding_id: str):
    """Related intelligence for a finding, using relationships that already exist
    in the graph. Answers 'what else does this connect to?' so users can move
    from a finding to the competitors, recommendations and other findings it
    touches. Nothing is inferred or invented — if no relationship exists, the
    list is empty."""
    graph = db.graph()
    claims = await graph.get_claims([finding_id])
    if not claims:
        raise HTTPException(404, "Finding not found")
    claim = claims[0]

    related_findings: list[dict] = []
    competitors: list[dict] = []
    recommendations: list[dict] = []

    # Recommendations / intelligence that cite this finding.
    try:
        for ins in await graph.insights_citing_claim(finding_id):
            entry = {"id": ins.id, "title": ins.title,
                     "confidence": round(ins.trust.confidence, 2)}
            if ins.kind.value == "recommendation":
                recommendations.append(entry)
    except Exception:  # noqa: BLE001
        pass

    # Sibling findings about the same subject and topic.
    try:
        siblings = await graph.claims(
            WORKSPACE, subject_entity_id=claim.subject_entity_id, limit=50)
        for c in siblings:
            if c.id == finding_id or c.topic != claim.topic:
                continue
            related_findings.append({
                "id": c.id, "statement": c.statement,
                "confidence": round(c.trust.confidence, 2),
                "topic": c.topic,
            })
        related_findings = related_findings[:6]
    except Exception:  # noqa: BLE001
        pass

    # Competitors of the subject organization, when the graph records them.
    try:
        entity = await graph.get_entity(claim.subject_entity_id)
        if entity is not None:
            edges = await graph.competitor_edges_for_org(
                WORKSPACE, entity.id, entity.name)
            for edge in edges[:6]:
                target = await graph.get_entity(edge.target_entity_id)
                if target is not None:
                    competitors.append({"id": target.id, "name": target.name})
    except Exception:  # noqa: BLE001
        pass

    return {"finding_id": finding_id,
            "related_findings": related_findings,
            "competitors": competitors,
            "recommendations": recommendations}


@router.get("/exports/report.pdf")
async def export_report_pdf(organization_id: str, kind: str = "executive"):
    """Server-side executive PDF. Organization ownership is verified before any
    data is read, so changing the id in the URL cannot expose another
    workspace's intelligence."""
    from fastapi.responses import Response
    from app.reports.exporters import REPORT_KINDS, build_report_pdf

    if kind not in REPORT_KINDS:
        raise HTTPException(422, f"unknown report kind; one of: {sorted(REPORT_KINDS)}")
    org = _org_or_404(await db.get_organization(organization_id))

    data = await _export_payload(org)
    pdf = build_report_pdf(kind, org.name, data)
    safe = "".join(c if c.isalnum() else "-" for c in org.name).strip("-").lower()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{safe or "organization"}-{kind}-report.pdf"'})


async def _export_payload(org) -> dict:
    """Collect the already-scoped intelligence a report needs. Every query is
    filtered by this workspace and organization."""
    graph = db.graph()
    counts: dict = {}
    recs: list[dict] = []
    findings: list[dict] = []
    conflicts: list[dict] = []
    try:
        insights = await graph.insights(WORKSPACE, org.id)
        for ins in insights:
            pub = _public_insight(ins)
            entry = {"title": pub["title"], "body": pub["body"],
                     "confidence": ins.trust.confidence}
            kindv = ins.kind.value
            if kindv == "recommendation":
                recs.append(entry)
            elif kindv == "dispute":
                if ins.debate_status not in ("resolved", "validated"):
                    conflicts.append(entry)
            elif ins.debate_status == "validated":
                findings.append(entry)
        counts = {
            "validated": len(findings),
            "recommendations": len(recs),
            "disputes_open": len(conflicts),
        }
    except Exception:  # noqa: BLE001 - a report must not fail on one section
        pass
    try:
        runs = await db.list_runs(WORKSPACE, organization_id=org.id)
        counts["runs"] = len(runs)
    except Exception:  # noqa: BLE001
        counts.setdefault("runs", 0)
    try:
        changes = await db.list_competitor_changes(
            WORKSPACE, organization_id=org.id)
    except Exception:  # noqa: BLE001
        changes = []
    try:
        ev = await twin_evidence(org.id)
        sources = ev.get("evidence", []) if isinstance(ev, dict) else []
    except Exception:  # noqa: BLE001
        sources = []

    recs.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    findings.sort(key=lambda f: f.get("confidence", 0), reverse=True)
    return {"counts": counts, "recommendations": recs, "findings": findings,
            "conflicts": conflicts, "competitor_changes": changes,
            "sources": sources}


@router.get("/exports/{dataset}.csv")
async def export_csv(dataset: str, organization_id: str):
    """Server-side CSV for a tabular dataset, scoped to one organization.
    Ownership is verified first; unknown datasets are rejected explicitly."""
    from fastapi.responses import Response
    from app.reports.exporters import CSV_DATASETS, build_csv

    if dataset not in CSV_DATASETS:
        raise HTTPException(422, f"unknown dataset; one of: {sorted(CSV_DATASETS)}")
    org = _org_or_404(await db.get_organization(organization_id))

    rows: list[dict] = []
    if dataset in ("findings", "recommendations"):
        claims = await db.graph().claims(WORKSPACE, subject_entity_id=org.root_entity_id,
                                         limit=500) if dataset == "findings" else []
        if dataset == "findings":
            for c in claims:
                rows.append({
                    "organization": org.name, "finding": c.statement,
                    "topic": c.topic,
                    "confidence": round(c.trust.confidence, 3),
                    "source_count": len(c.evidence_ids),
                    "status": c.status, "as_of": c.as_of or "",
                    "created_at": c.created_at})
        else:
            for ins in await db.graph().insights(WORKSPACE, org.id):
                if ins.kind.value != "recommendation":
                    continue
                pub = _public_insight(ins)
                rows.append({
                    "organization": org.name, "recommendation": pub["title"],
                    "confidence": round(ins.trust.confidence, 3),
                    "supporting_findings": len(ins.claim_ids),
                    "status": ins.debate_status})
    elif dataset == "competitor_changes":
        for c in await db.list_competitor_changes(WORKSPACE, organization_id=org.id):
            rows.append({
                "organization": org.name,
                "competitor": c.get("competitor_name"),
                "category": c.get("category"), "severity": c.get("severity"),
                "summary": c.get("summary"), "before": c.get("before") or "",
                "after": c.get("after") or "",
                "acknowledged": c.get("acknowledged"),
                "detected_at": c.get("detected_at")})
    elif dataset == "leads":
        for lead in await db.list_leads(WORKSPACE):
            if lead.get("organization_id") not in (None, org.id):
                continue
            rows.append({
                "organization": org.name, "company": lead.get("company_name"),
                "domain": lead.get("domain") or "",
                "industry": lead.get("industry") or "",
                "stage": lead.get("stage"), "score": lead.get("score"),
                "score_band": lead.get("score_band"),
                "created_at": lead.get("created_at")})
    elif dataset == "website_audits":
        for a in await db.list_website_audits(WORKSPACE, organization_id=org.id):
            rows.append({
                "organization": org.name, "url": a.get("url"),
                "ok": a.get("ok"),
                "overall_score": (a.get("scores") or {}).get("overall", ""),
                "created_at": a.get("created_at")})

    body = build_csv(dataset, rows)
    safe = "".join(c if c.isalnum() else "-" for c in org.name).strip("-").lower()
    return Response(
        content=body, media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="{safe or "organization"}-{dataset}.csv"'})


@router.get("/twins/{org_id}/opportunity-states")
async def opportunity_states(org_id: str):
    """Lifecycle overlay (status/owner) for this organization's derived
    opportunities. Opportunities themselves stay derived from the graph."""
    org = _org_or_404(await db.get_organization(org_id))
    return {"states": await db.get_opportunity_states(WORKSPACE, org.id),
            "valid_statuses": list(db.OPPORTUNITY_STATUSES)}


class OpportunityStateIn(BaseModel):
    opportunity_key: str
    status: str | None = None
    owner: str | None = None


@router.post("/twins/{org_id}/opportunity-states")
async def set_opportunity_state(org_id: str, body: OpportunityStateIn):
    """Record a lifecycle decision for one derived opportunity."""
    org = _org_or_404(await db.get_organization(org_id))
    if not body.opportunity_key.strip():
        raise HTTPException(422, "opportunity_key is required")
    try:
        return await db.set_opportunity_state(
            WORKSPACE, org.id, body.opportunity_key.strip(),
            status=body.status, owner=body.owner)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/search")
async def workspace_search(q: str, org_id: str | None = None, limit: int = 10):
    """Cross-module search over everything the platform actually persists:
    organizations, findings, intelligence, recommendations, competitors,
    monitoring changes, leads and website audits.

    Extends the existing graph search rather than introducing a second search
    engine. Every query is workspace-scoped, and when an organization is supplied
    it is ownership-checked first so search can never surface another tenant's
    records. Insight text is sanitized on the way out, so internal reviewer
    wording never appears in results."""
    org = _org_or_404(await db.get_organization(org_id)) if org_id else None
    org_key = org.id if org else ""
    results = await db.graph().workspace_search(WORKSPACE, org_key, q, limit)

    # Sanitize graph text (search bypasses the normal insight read path).
    for bucket in ("insights", "recommendations"):
        cleaned = []
        for item in results.get(bucket, []):
            body, note = split_validation_note(item.get("body", "") or "")
            item["body"] = body
            item["validation_note"] = note
            cleaned.append(item)
        results[bucket] = cleaned

    needle = (q or "").strip().lower()
    competitors: list[dict] = []
    monitoring: list[dict] = []
    leads: list[dict] = []
    audits: list[dict] = []

    if needle:
        # Competitors discovered for this organization.
        if org is not None and org.root_entity_id:
            try:
                graph = db.graph()
                for edge in await graph.competitor_edges_for_org(
                        WORKSPACE, org.root_entity_id, org.name):
                    ent = await graph.get_entity(edge.target_entity_id)
                    if ent and needle in ent.name.lower():
                        competitors.append({"id": ent.id, "name": ent.name})
            except Exception:  # noqa: BLE001 - one bucket must not break search
                pass

        # Monitoring changes (competitor name, category or summary).
        try:
            for c in await db.list_competitor_changes(
                    WORKSPACE, organization_id=org.id if org else None):
                hay = " ".join(str(c.get(k, "")) for k in
                               ("competitor_name", "category", "summary")).lower()
                if needle in hay:
                    monitoring.append({
                        "id": c.get("id"), "competitor": c.get("competitor_name"),
                        "category": c.get("category"), "severity": c.get("severity"),
                        "summary": c.get("summary"),
                        "detected_at": c.get("detected_at")})
        except Exception:  # noqa: BLE001
            pass

        # CRM leads (company or domain).
        try:
            for lead in await db.list_leads(WORKSPACE):
                if org is not None and lead.get("organization_id") not in (None, org.id):
                    continue
                hay = f"{lead.get('company_name','')} {lead.get('domain','')}".lower()
                if needle in hay:
                    leads.append({
                        "id": lead.get("id"), "company": lead.get("company_name"),
                        "domain": lead.get("domain"), "stage": lead.get("stage"),
                        "score": lead.get("score"),
                        "score_band": lead.get("score_band")})
        except Exception:  # noqa: BLE001
            pass

        # Website audits (by URL).
        try:
            for a in await db.list_website_audits(
                    WORKSPACE, organization_id=org.id if org else None):
                if needle in str(a.get("url", "")).lower():
                    audits.append({
                        "id": a.get("id"), "url": a.get("url"),
                        "ok": a.get("ok"),
                        "overall_score": (a.get("scores") or {}).get("overall"),
                        "created_at": a.get("created_at")})
        except Exception:  # noqa: BLE001
            pass

    results["competitors"] = competitors[:limit]
    results["monitoring"] = monitoring[:limit]
    results["leads"] = leads[:limit]
    results["website_audits"] = audits[:limit]
    results["organization_scoped"] = org is not None
    return results


@router.get("/system/performance")
async def system_performance():
    """Observability (spec §47): live cache hit-rates, queue concurrency, and
    429/backoff counters. Read-only; safe to poll. Grounds the Priority-Zero
    performance claims in real numbers rather than assertions."""
    from app.core.throttle import all_stats
    return all_stats()


class WebsiteAuditIn(BaseModel):
    url: str
    organization_id: str | None = None


@router.post("/tools/website-audit")
async def website_audit(body: WebsiteAuditIn):
    """Real, on-demand website/SEO/tech/security audit (Semrush-class technical
    audit). Fetches the live page and analyzes it — genuinely measured data, no
    fabrication. Persists each audit as a timestamped snapshot so the SEO module
    has history + change detection. In environments without outbound network the
    fetch fails honestly with ok=False rather than returning fake numbers.

    Feeds three products from one analysis: SEO audit, competitor tech/messaging
    snapshot, and company enrichment.
    """
    from app.analyzers.website_intel import audit_website
    result = await audit_website(body.url)
    try:
        audit_id = await db.save_website_audit(
            WORKSPACE, body.url, ok=bool(result.get("ok")),
            scores=result.get("scores", {}), analysis=result.get("analysis", {}),
            organization_id=body.organization_id)
        result["audit_id"] = audit_id
    except Exception:  # noqa: BLE001 - persistence best-effort, never blocks audit
        pass
    return result


@router.get("/website-audits")
async def website_audit_history(organization_id: str | None = None,
                                url: str | None = None):
    """Audit history — every persisted snapshot, newest first. Powers SEO trend
    tracking and page-over-time change detection."""
    audits = await db.list_website_audits(
        WORKSPACE, organization_id=organization_id, url=url)
    return {"audits": audits, "count": len(audits)}


@router.get("/website-audits/{audit_id}")
async def website_audit_detail(audit_id: str):
    """Full stored audit — all measured signals + evidence-derived issues."""
    audit = await db.get_website_audit(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit


class CollectIn(BaseModel):
    target: str


@router.post("/tools/collect")
async def collect_intelligence(body: CollectIn):
    """Fan out across free public-data connectors for a target (a domain,
    company, or owner/repo) and return normalized, real collected intelligence.
    Each connector reports availability honestly; unreachable/empty sources
    return available=False with a note rather than fabricated data (Rule 2).
    """
    from app.connectors.base import collect_all
    from app.connectors.github import GitHubConnector

    connectors = [GitHubConnector()]
    results = await collect_all(connectors, body.target)
    return {"target": body.target,
            "connectors": {k: v.as_dict() for k, v in results.items()}}


@router.get("/tools")
async def tools():
    """The Tool Layer, self-describing (rule 4 documentation)."""
    return registry.describe()


# ============================ Apollo / Sales Intelligence ====================

class DiscoverIn(BaseModel):
    company_name: str
    domain: str
    industry: str | None = None
    location: str | None = None
    employee_range: str | None = None
    icp_industry: str | None = None
    icp_employee_range: str | None = None


@router.post("/sales/discover")
async def sales_discover(body: DiscoverIn):
    """Discover + enrich + score a company into the CRM. Enrichment is real
    (website analysis + connectors); the score is evidence-derived; public
    contacts are collected where they exist and marked not_found otherwise —
    emails are never fabricated (Rule 2). Persisted as a Lead."""
    from app.analyzers.sales_intel import enrich_company
    from app.analyzers.lead_scoring import score_lead

    enrichment = await enrich_company(
        body.domain, industry=body.industry, employee_range=body.employee_range)
    icp = {}
    if body.icp_industry:
        icp["industry"] = body.icp_industry
    if body.icp_employee_range:
        icp["employee_range"] = body.icp_employee_range
    scored = score_lead(enrichment, icp=icp or None)

    lead_id = await db.create_lead(
        WORKSPACE, company_name=body.company_name, domain=body.domain,
        industry=body.industry, location=body.location,
        employee_range=body.employee_range, enrichment=enrichment,
        score=scored.score, score_band=scored.band,
        score_breakdown=scored.as_dict())

    # persist any public contacts discovered during enrichment
    contacts = enrichment.get("contacts", [])
    if contacts:
        await db.add_contacts(WORKSPACE, lead_id, contacts)

    return {"lead_id": lead_id, "score": scored.score, "band": scored.band,
            "score_breakdown": scored.as_dict(),
            "contacts_found": len(contacts),
            "enrichment_ok": enrichment.get("website") is not None}


@router.get("/sales/leads")
async def sales_leads(stage: str | None = None, industry: str | None = None,
                      band: str | None = None, min_score: int | None = None):
    """Lead database with filters (stage, industry, score band, min score)."""
    leads = await db.list_leads(WORKSPACE, stage=stage, industry=industry,
                                band=band, min_score=min_score)
    return {"leads": leads, "count": len(leads)}


@router.get("/sales/leads/{lead_id}")
async def sales_lead_detail(lead_id: str):
    """Full lead: enrichment, score breakdown, contacts, notes, tasks, activity."""
    lead = await db.get_lead(WORKSPACE, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


class StageIn(BaseModel):
    stage: str


@router.post("/sales/leads/{lead_id}/stage")
async def sales_move_stage(lead_id: str, body: StageIn):
    valid = {"discovered", "qualified", "contacted", "meeting", "proposal", "won", "lost"}
    if body.stage not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid stage. One of: {sorted(valid)}")
    if not await db.move_lead_stage(WORKSPACE, lead_id, body.stage):
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"ok": True, "stage": body.stage}


class NoteIn(BaseModel):
    body: str


@router.post("/sales/leads/{lead_id}/notes")
async def sales_add_note(lead_id: str, body: NoteIn):
    note_id = await db.add_note(WORKSPACE, lead_id, body.body)
    return {"ok": True, "note_id": note_id}


class TaskIn(BaseModel):
    title: str
    due_date: str | None = None


@router.post("/sales/leads/{lead_id}/tasks")
async def sales_add_task(lead_id: str, body: TaskIn):
    task_id = await db.add_task(WORKSPACE, lead_id, body.title, body.due_date)
    return {"ok": True, "task_id": task_id}


@router.post("/sales/tasks/{task_id}/complete")
async def sales_complete_task(task_id: str):
    if not await db.complete_task(WORKSPACE, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


class EmailIn(BaseModel):
    kind: str = "cold"
    sender: str = "our team"
    include_competitor_context: bool = False


@router.post("/sales/leads/{lead_id}/email")
async def sales_generate_email(lead_id: str, body: EmailIn):
    """Generate a personalized outreach email grounded in the lead's REAL
    enrichment via the NVIDIA-backed LLM router. Requires a live LLM key; returns
    a clear message if unavailable rather than a fabricated email."""
    lead = await db.get_lead(WORKSPACE, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # competitor context (unified graph: outreach can reference Crayon changes)
    comp_ctx = None
    if body.include_competitor_context and lead.get("organization_id"):
        changes = await db.list_competitor_changes(
            WORKSPACE, organization_id=lead["organization_id"], limit=3)
        if changes:
            comp_ctx = "; ".join(c["summary"] for c in changes)

    try:
        provider = build_provider()
        llm = LLMRouter(provider, ledger=CostLedger(), run_id=f"email-{lead_id}")
        from app.analyzers.sales_intel import generate_outreach_email
        email = await generate_outreach_email(
            llm, lead=lead, kind=body.kind, sender=body.sender,
            competitor_context=comp_ctx)
        await db.log_email_activity(WORKSPACE, lead_id, email.get("subject", ""))
        return {"ok": True, "email": email}
    except Exception as exc:  # noqa: BLE001 - honest failure, no fake email
        return {"ok": False,
                "error": "AI email generation requires a configured LLM provider.",
                "detail": str(exc)[:200]}


@router.get("/sales/leads/{lead_id}/sequence")
async def sales_sequence(lead_id: str):
    """A multi-step outreach sequence scaffold for the lead."""
    lead = await db.get_lead(WORKSPACE, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    from app.analyzers.sales_intel import build_sequence
    return {"sequence": build_sequence(lead)}


@router.get("/sales/pipeline")
async def sales_pipeline():
    """Pipeline + conversion + lead-quality report."""
    return await db.pipeline_report(WORKSPACE)
