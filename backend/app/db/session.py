"""Database access. From Phase 1 the Intelligence Graph is the system of
record, so persistence defaults ON: DATABASE_URL falls back to a local SQLite
file for zero-infra dev; docker-compose provides Postgres/pgvector.

TODO(prod): enforce Postgres in `environment=prod` (SQLite is a dev
convenience only — Blueprint says Postgres day one; this fallback exists so
the repo runs with zero setup and tests run hermetically).
"""
import json
import uuid

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import (Base, CompetitorChange, CompetitorSnapshot, Contact, CrmActivity, CrmNote, CrmTask, Lead, Organization, OpportunityState, Run, WebsiteAudit, Workspace, utcnow)
from app.graph.models import EventRow, JobRow
from app.graph.store import IntelligenceGraph

log = get_logger("db")
_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_graph: IntelligenceGraph | None = None

DEFAULT_WORKSPACE_ID = "ws_default"
_DEV_FALLBACK_URL = "sqlite+aiosqlite:///./sentient.db"


def enabled() -> bool:
    return _sessionmaker is not None


def graph() -> IntelligenceGraph:
    if _graph is None:
        raise RuntimeError("database not initialized — call init_db() first")
    return _graph


def _sync_dsn(dsn: str) -> str:
    return dsn.replace("sqlite+aiosqlite", "sqlite").replace("postgresql+asyncpg", "postgresql")


def _run_alembic_upgrade(dsn: str) -> None:
    """Schema management is Alembic's job from Phase 2 (spec M0)."""
    from alembic import command
    from alembic.config import Config
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sync_dsn(dsn))
    command.upgrade(cfg, "head")


async def init_db(url: str | None = None, *, use_alembic: bool | None = None) -> None:
    global _engine, _sessionmaker, _graph
    dsn = url or get_settings().database_url or _DEV_FALLBACK_URL
    _engine = create_async_engine(dsn)
    if dsn.startswith("sqlite"):
        # SQLite does not enforce FKs unless told to (junction integrity — C3)
        @event.listens_for(_engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    import app.graph.models  # noqa: F401  register graph tables on Base
    if use_alembic is None:
        use_alembic = get_settings().environment != "test"
    if use_alembic:
        import asyncio
        await asyncio.to_thread(_run_alembic_upgrade, dsn)
    else:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with _sessionmaker() as s:
        if await s.get(Workspace, DEFAULT_WORKSPACE_ID) is None:
            s.add(Workspace(id=DEFAULT_WORKSPACE_ID))
            await s.commit()
    _graph = IntelligenceGraph(_sessionmaker)
    # S6: persist every bus event to the outbox table (durable SSE/replay)
    from app.core.events import bus
    if _persist_event not in bus._subscribers:
        bus.subscribe(_persist_event)
    log.info("persistence enabled dsn=%s", dsn.split("@")[-1])


async def _persist_event(event) -> None:
    if _sessionmaker is None:
        return
    try:
        async with _sessionmaker() as s:
            s.add(EventRow(run_id=event.run_id, type=event.type,
                           payload=event.payload, at=event.at))
            await s.commit()
    except Exception:      # event persistence must never break a run
        pass


async def upsert_job(job_id: str, *, kind: str = "run", status: str = "running",
                     payload: dict | None = None, result: dict | None = None,
                     error: str | None = None) -> None:
    if _sessionmaker is None:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with _sessionmaker() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                row = JobRow(id=job_id, kind=kind, status=status,
                             payload=payload or {}, result=result or {},
                             error=error, heartbeat_at=now, created_at=now)
                s.add(row)
            else:
                row.status = status
                row.heartbeat_at = now
                if result is not None:
                    row.result = result
                if error is not None:
                    row.error = error
            await s.commit()
    except Exception as exc:
        log.warning("job upsert failed: %s", exc)


async def get_job(job_id: str):
    if _sessionmaker is None:
        return None
    async with _sessionmaker() as s:
        return await s.get(JobRow, job_id)


async def reap_stale_jobs(timeout_seconds: int = 120) -> int:
    """Mark 'running' jobs with a stale heartbeat as failed (crash recovery)."""
    if _sessionmaker is None:
        return 0
    from datetime import datetime, timedelta, timezone
    from app.graph.models import JobRow
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=timeout_seconds)).isoformat()
    async with _sessionmaker() as s:
        rows = (await s.execute(select(JobRow).where(
            JobRow.status == "running",
            JobRow.heartbeat_at < cutoff))).scalars().all()
        for row in rows:
            row.status, row.error = "failed", "reaped: heartbeat timeout"
        await s.commit()
        if rows:
            log.warning("reaped %d stale jobs", len(rows))
        return len(rows)


async def prune_events(older_than_days: int = 14) -> int:
    """Event outbox retention (audit B-item). claim_transitions is lineage of
    record and lives in its own retention-EXEMPT table — never touched here."""
    if _sessionmaker is None:
        return 0
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete as sa_delete
    from app.graph.models import EventRow
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=older_than_days)).isoformat()
    async with _sessionmaker() as s:
        result = await s.execute(sa_delete(EventRow).where(EventRow.at < cutoff))
        await s.commit()
        return result.rowcount or 0


async def events_for_run(run_id: str, after_seq: int = 0) -> list[dict]:
    if _sessionmaker is None:
        return []
    async with _sessionmaker() as s:
        rows = (await s.execute(select(EventRow)
                                .where(EventRow.run_id == run_id,
                                       EventRow.seq > after_seq)
                                .order_by(EventRow.seq))).scalars().all()
        return [{"seq": r.seq, "type": r.type, "run_id": r.run_id,
                 "payload": r.payload, "at": r.at} for r in rows]


async def get_or_create_organization(workspace_id: str, name: str, *,
                                     website: str | None = None,
                                     industry: str | None = None,
                                     root_entity_id: str | None = None) -> Organization:
    async with _sessionmaker() as s:
        row = (await s.execute(select(Organization).where(
            Organization.workspace_id == workspace_id, Organization.name == name,
        ))).scalar_one_or_none()
        if row is None:
            row = Organization(id=uuid.uuid4().hex[:32], workspace_id=workspace_id,
                               name=name, website=website, industry=industry,
                               root_entity_id=root_entity_id)
            s.add(row)
            await s.commit()
        elif root_entity_id and not row.root_entity_id:
            row.root_entity_id = root_entity_id   # backfill legacy rows at intake
            await s.commit()
        return row


async def get_organization(org_id: str) -> Organization | None:
    async with _sessionmaker() as s:
        return await s.get(Organization, org_id)


async def list_organizations(workspace_id: str) -> list[dict]:
    async with _sessionmaker() as s:
        rows = (await s.execute(select(Organization).where(
            Organization.workspace_id == workspace_id)
            .order_by(Organization.created_at.desc()))).scalars().all()
        return [{"id": r.id, "name": r.name, "website": r.website,
                 "industry": r.industry, "created_at": str(r.created_at)} for r in rows]


async def list_runs(workspace_id: str, organization_id: str | None = None,
                    limit: int = 50) -> list[dict]:
    """Research history. result is stored as a JSON string; parse defensively."""
    if _sessionmaker is None:
        return []
    async with _sessionmaker() as s:
        q = select(Run).where(Run.workspace_id == workspace_id)
        if organization_id:
            q = q.where(Run.organization_id == organization_id)
        rows = (await s.execute(q.order_by(Run.created_at.desc())
                                .limit(limit))).scalars().all()
    out = []
    for r in rows:
        try:
            result = json.loads(r.result) if r.result else {}
        except (json.JSONDecodeError, TypeError):
            result = {}
        out.append({"run_id": r.id, "organization_id": r.organization_id,
                    "status": r.status, "created_at": str(r.created_at),
                    "brief": r.request, "manifest": r.manifest,
                    "costs": r.costs,
                    "playbook": result.get("playbook"),
                    "summary": {k: result.get(k) for k in
                                ("claims", "edges", "recommendations",
                                 "hypotheses", "searches", "seconds")
                                if k in result}})
    return out


async def persist_v2_run(run_id: str, workspace_id: str, org_id: str,
                         brief: dict, manifest: dict, costs: dict, stats: dict) -> None:
    async with _sessionmaker() as s:
        s.add(Run(id=run_id, workspace_id=workspace_id, organization_id=org_id,
                  request=brief, manifest=manifest, costs=costs,
                  status="completed", result=json.dumps(stats, default=str)))
        await s.commit()


# ---- legacy v1 support (kept until frontend migrates; then delete) --------
async def persist_run(ctx, results: dict) -> None:
    if _sessionmaker is None:
        return
    try:
        org = await get_or_create_organization(DEFAULT_WORKSPACE_ID,
                                               ctx.request.company_name,
                                               website=str(ctx.request.website),
                                               industry=ctx.request.industry)
        async with _sessionmaker() as s:
            s.add(Run(id=ctx.run_id, workspace_id=DEFAULT_WORKSPACE_ID,
                      organization_id=org.id,
                      request=ctx.request.model_dump(mode="json"),
                      manifest=results["meta"]["manifest"],
                      costs=results["meta"]["costs"],
                      status="degraded" if results["meta"]["degraded"] else "completed",
                      result=json.dumps(results, default=str)))
            await s.commit()
    except Exception as exc:
        log.warning("run_id=%s persist failed: %s", ctx.run_id, exc)


# ---- Website audit persistence (Semrush module) ----------------------------
async def save_website_audit(workspace_id: str, url: str, *, ok: bool,
                             scores: dict, analysis: dict,
                             organization_id: str | None = None) -> str:
    """Persist one audit snapshot. History powers SEO trends + change detection."""
    audit_id = uuid.uuid4().hex[:32]
    async with _sessionmaker() as s:
        s.add(WebsiteAudit(
            id=audit_id, workspace_id=workspace_id, organization_id=organization_id,
            url=url, ok=ok, scores=scores or {}, analysis=analysis or {},
            issue_count=len((analysis or {}).get("issues", [])),
        ))
        await s.commit()
    return audit_id


async def list_website_audits(workspace_id: str, *, organization_id: str | None = None,
                              url: str | None = None, limit: int = 50) -> list[dict]:
    if _sessionmaker is None:
        return []
    async with _sessionmaker() as s:
        q = select(WebsiteAudit).where(WebsiteAudit.workspace_id == workspace_id)
        if organization_id:
            q = q.where(WebsiteAudit.organization_id == organization_id)
        if url:
            q = q.where(WebsiteAudit.url == url)
        rows = (await s.execute(q.order_by(WebsiteAudit.created_at.desc())
                                .limit(limit))).scalars().all()
    return [{"id": r.id, "url": r.url, "ok": r.ok, "scores": r.scores,
             "issue_count": r.issue_count, "created_at": str(r.created_at)}
            for r in rows]


async def get_website_audit(audit_id: str) -> dict | None:
    if _sessionmaker is None:
        return None
    async with _sessionmaker() as s:
        r = (await s.execute(select(WebsiteAudit).where(
            WebsiteAudit.id == audit_id))).scalar_one_or_none()
    if r is None:
        return None
    return {"id": r.id, "url": r.url, "ok": r.ok, "scores": r.scores,
            "analysis": r.analysis, "issue_count": r.issue_count,
            "organization_id": r.organization_id, "created_at": str(r.created_at)}


# ---- Competitor monitoring persistence (Crayon module) ---------------------
async def latest_competitor_snapshot(workspace_id: str, url: str) -> dict | None:
    if _sessionmaker is None:
        return None
    async with _sessionmaker() as s:
        r = (await s.execute(select(CompetitorSnapshot)
             .where(CompetitorSnapshot.workspace_id == workspace_id,
                    CompetitorSnapshot.url == url)
             .order_by(CompetitorSnapshot.created_at.desc()).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    return {"id": r.id, "signals": r.signals, "content_hash": r.content_hash,
            "created_at": str(r.created_at)}


async def save_competitor_snapshot(workspace_id: str, organization_id: str, *,
                                   competitor_name: str, url: str, page_type: str,
                                   signals: dict, content_hash: str,
                                   competitor_entity_id: str | None = None) -> str:
    snap_id = uuid.uuid4().hex[:32]
    async with _sessionmaker() as s:
        s.add(CompetitorSnapshot(
            id=snap_id, workspace_id=workspace_id, organization_id=organization_id,
            competitor_entity_id=competitor_entity_id, competitor_name=competitor_name,
            url=url, page_type=page_type, signals=signals, content_hash=content_hash))
        await s.commit()
    return snap_id


async def save_competitor_changes(workspace_id: str, organization_id: str, *,
                                  competitor_name: str, url: str,
                                  changes: list[dict]) -> list[str]:
    ids: list[str] = []
    async with _sessionmaker() as s:
        for ch in changes:
            cid = uuid.uuid4().hex[:32]
            ids.append(cid)
            s.add(CompetitorChange(
                id=cid, workspace_id=workspace_id, organization_id=organization_id,
                competitor_name=competitor_name, url=url,
                category=ch["category"], severity=ch["severity"],
                summary=ch["summary"], before=ch.get("before"), after=ch.get("after")))
        await s.commit()
    return ids


async def list_competitor_changes(workspace_id: str, *, organization_id: str | None = None,
                                  competitor_name: str | None = None,
                                  unacknowledged_only: bool = False,
                                  limit: int = 100) -> list[dict]:
    if _sessionmaker is None:
        return []
    async with _sessionmaker() as s:
        q = select(CompetitorChange).where(CompetitorChange.workspace_id == workspace_id)
        if organization_id:
            q = q.where(CompetitorChange.organization_id == organization_id)
        if competitor_name:
            q = q.where(CompetitorChange.competitor_name == competitor_name)
        if unacknowledged_only:
            q = q.where(CompetitorChange.acknowledged == False)  # noqa: E712
        rows = (await s.execute(q.order_by(CompetitorChange.detected_at.desc())
                                .limit(limit))).scalars().all()
    return [{"id": r.id, "competitor_name": r.competitor_name, "url": r.url,
             "category": r.category, "severity": r.severity, "summary": r.summary,
             "before": r.before, "after": r.after, "acknowledged": r.acknowledged,
             "detected_at": str(r.detected_at)} for r in rows]


async def acknowledge_competitor_change(workspace_id: str, change_id: str) -> bool:
    if _sessionmaker is None:
        return False
    async with _sessionmaker() as s:
        r = (await s.execute(select(CompetitorChange).where(
            CompetitorChange.workspace_id == workspace_id,
            CompetitorChange.id == change_id))).scalar_one_or_none()
        if r is None:
            return False
        r.acknowledged = True
        await s.commit()
    return True


# ---- Apollo / Sales CRM persistence ----------------------------------------
async def _log_activity(s, workspace_id: str, lead_id: str, kind: str, summary: str):
    s.add(CrmActivity(id=uuid.uuid4().hex[:32], workspace_id=workspace_id,
                      lead_id=lead_id, kind=kind, summary=summary))


async def create_lead(workspace_id: str, *, company_name: str, domain: str | None,
                      industry: str | None, location: str | None,
                      employee_range: str | None, enrichment: dict,
                      score: int, score_band: str, score_breakdown: dict,
                      organization_id: str | None = None,
                      source: str = "discovery") -> str:
    lead_id = uuid.uuid4().hex[:32]
    async with _sessionmaker() as s:
        s.add(Lead(id=lead_id, workspace_id=workspace_id, organization_id=organization_id,
                   company_name=company_name, domain=domain, industry=industry,
                   location=location, employee_range=employee_range,
                   enrichment=enrichment, score=score, score_band=score_band,
                   score_breakdown=score_breakdown, source=source))
        await s.flush()  # lead row exists before activity FK references it
        await _log_activity(s, workspace_id, lead_id, "enriched",
                            f"Lead created and enriched · score {score} ({score_band})")
        await s.commit()
    return lead_id


async def list_leads(workspace_id: str, *, stage: str | None = None,
                     industry: str | None = None, min_score: int | None = None,
                     band: str | None = None, limit: int = 200) -> list[dict]:
    if _sessionmaker is None:
        return []
    async with _sessionmaker() as s:
        q = select(Lead).where(Lead.workspace_id == workspace_id)
        if stage:
            q = q.where(Lead.stage == stage)
        if industry:
            q = q.where(Lead.industry == industry)
        if band:
            q = q.where(Lead.score_band == band)
        if min_score is not None:
            q = q.where(Lead.score >= min_score)
        rows = (await s.execute(q.order_by(Lead.score.desc()).limit(limit))).scalars().all()
    return [_lead_summary(r) for r in rows]


def _lead_summary(r: "Lead") -> dict:
    return {"id": r.id, "company_name": r.company_name, "domain": r.domain,
            "industry": r.industry, "location": r.location,
            "employee_range": r.employee_range, "score": r.score,
            "score_band": r.score_band, "stage": r.stage,
            "created_at": str(r.created_at)}


async def get_lead(workspace_id: str, lead_id: str) -> dict | None:
    if _sessionmaker is None:
        return None
    async with _sessionmaker() as s:
        r = (await s.execute(select(Lead).where(
            Lead.workspace_id == workspace_id, Lead.id == lead_id))).scalar_one_or_none()
        if r is None:
            return None
        contacts = (await s.execute(select(Contact).where(Contact.lead_id == lead_id))).scalars().all()
        notes = (await s.execute(select(CrmNote).where(CrmNote.lead_id == lead_id)
                 .order_by(CrmNote.created_at.desc()))).scalars().all()
        tasks = (await s.execute(select(CrmTask).where(CrmTask.lead_id == lead_id)
                 .order_by(CrmTask.created_at.desc()))).scalars().all()
        acts = (await s.execute(select(CrmActivity).where(CrmActivity.lead_id == lead_id)
                .order_by(CrmActivity.created_at.desc()).limit(50))).scalars().all()
    d = _lead_summary(r)
    d.update({
        "enrichment": r.enrichment, "score_breakdown": r.score_breakdown,
        "contacts": [{"id": c.id, "name": c.name, "title": c.title,
                      "department": c.department, "email": c.email,
                      "email_status": c.email_status, "linkedin": c.linkedin,
                      "source": c.source} for c in contacts],
        "notes": [{"id": n.id, "body": n.body, "author": n.author,
                   "created_at": str(n.created_at)} for n in notes],
        "tasks": [{"id": t.id, "title": t.title, "due_date": t.due_date,
                   "done": t.done, "created_at": str(t.created_at)} for t in tasks],
        "activities": [{"id": a.id, "kind": a.kind, "summary": a.summary,
                        "created_at": str(a.created_at)} for a in acts],
    })
    return d


async def add_contacts(workspace_id: str, lead_id: str, contacts: list[dict]) -> int:
    async with _sessionmaker() as s:
        for c in contacts:
            s.add(Contact(id=uuid.uuid4().hex[:32], workspace_id=workspace_id,
                          lead_id=lead_id, name=c.get("name", ""), title=c.get("title"),
                          department=c.get("department"), seniority=c.get("seniority"),
                          email=c.get("email"), email_status=c.get("email_status", "not_found"),
                          linkedin=c.get("linkedin"), source=c.get("source")))
        await s.commit()
    return len(contacts)


async def move_lead_stage(workspace_id: str, lead_id: str, stage: str) -> bool:
    async with _sessionmaker() as s:
        r = (await s.execute(select(Lead).where(
            Lead.workspace_id == workspace_id, Lead.id == lead_id))).scalar_one_or_none()
        if r is None:
            return False
        old = r.stage
        r.stage = stage
        r.updated_at = utcnow()
        await _log_activity(s, workspace_id, lead_id, "stage_change",
                            f"Stage moved: {old} → {stage}")
        await s.commit()
    return True


async def add_note(workspace_id: str, lead_id: str, body: str, author: str = "user") -> str:
    note_id = uuid.uuid4().hex[:32]
    async with _sessionmaker() as s:
        s.add(CrmNote(id=note_id, workspace_id=workspace_id, lead_id=lead_id,
                      body=body, author=author))
        await _log_activity(s, workspace_id, lead_id, "note", body[:80])
        await s.commit()
    return note_id


async def add_task(workspace_id: str, lead_id: str, title: str,
                   due_date: str | None = None) -> str:
    task_id = uuid.uuid4().hex[:32]
    async with _sessionmaker() as s:
        s.add(CrmTask(id=task_id, workspace_id=workspace_id, lead_id=lead_id,
                      title=title, due_date=due_date))
        await _log_activity(s, workspace_id, lead_id, "task", f"Task: {title}")
        await s.commit()
    return task_id


async def complete_task(workspace_id: str, task_id: str) -> bool:
    async with _sessionmaker() as s:
        r = (await s.execute(select(CrmTask).where(
            CrmTask.workspace_id == workspace_id, CrmTask.id == task_id))).scalar_one_or_none()
        if r is None:
            return False
        r.done = True
        await s.commit()
    return True


async def log_email_activity(workspace_id: str, lead_id: str, subject: str) -> None:
    async with _sessionmaker() as s:
        await _log_activity(s, workspace_id, lead_id, "email",
                            f"AI email drafted: {subject}")
        await s.commit()


async def pipeline_report(workspace_id: str) -> dict:
    if _sessionmaker is None:
        return {}
    async with _sessionmaker() as s:
        rows = (await s.execute(select(Lead).where(Lead.workspace_id == workspace_id))).scalars().all()
    stages = ["discovered", "qualified", "contacted", "meeting", "proposal", "won", "lost"]
    by_stage = {st: 0 for st in stages}
    by_band = {"priority": 0, "hot": 0, "warm": 0, "cold": 0}
    for r in rows:
        by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
        by_band[r.score_band] = by_band.get(r.score_band, 0) + 1
    total = len(rows)
    won = by_stage.get("won", 0)
    contacted = sum(by_stage.get(s, 0) for s in ["contacted", "meeting", "proposal", "won", "lost"])
    return {
        "total_leads": total,
        "by_stage": by_stage,
        "by_band": by_band,
        "conversion_rate": round(won / total, 3) if total else 0.0,
        "contact_rate": round(contacted / total, 3) if total else 0.0,
        "avg_score": round(sum(r.score for r in rows) / total, 1) if total else 0.0,
        "has_data": total > 0,
    }


async def competitor_monitoring_status(workspace_id: str, organization_id: str) -> dict:
    """Summarize monitoring state per watched URL for an org: snapshot count,
    first/last scan, and how many changes have been detected. Powers the
    'baseline created / monitoring active / waiting for next comparison' UX so
    the page never shows a bare empty state after a first scan."""
    if _sessionmaker is None:
        return {"watched": [], "total_snapshots": 0}
    async with _sessionmaker() as s:
        snaps = (await s.execute(select(CompetitorSnapshot).where(
            CompetitorSnapshot.workspace_id == workspace_id,
            CompetitorSnapshot.organization_id == organization_id)
            .order_by(CompetitorSnapshot.created_at.asc()))).scalars().all()
        changes = (await s.execute(select(CompetitorChange).where(
            CompetitorChange.workspace_id == workspace_id,
            CompetitorChange.organization_id == organization_id))).scalars().all()
    per_url: dict[str, dict] = {}
    for sn in snaps:
        e = per_url.setdefault(sn.url, {
            "url": sn.url, "competitor_name": sn.competitor_name,
            "snapshot_count": 0, "first_scan": None, "last_scan": None,
            "change_count": 0})
        e["snapshot_count"] += 1
        ts = str(sn.created_at)
        e["first_scan"] = e["first_scan"] or ts
        e["last_scan"] = ts
    for ch in changes:
        if ch.url in per_url:
            per_url[ch.url]["change_count"] += 1
    watched = list(per_url.values())
    for w in watched:
        if w["snapshot_count"] <= 1:
            w["status"] = "baseline"      # baseline captured, awaiting next scan
        elif w["change_count"] > 0:
            w["status"] = "changes_detected"
        else:
            w["status"] = "stable"         # multiple scans, no changes yet
    return {"watched": watched, "total_snapshots": len(snaps),
            "watched_count": len(watched)}


async def find_lead_by_organization(workspace_id: str,
                                    organization_id: str) -> str | None:
    """Return an existing lead id for an organization, if one is already in the
    CRM. Lets the investigation enrichment stay idempotent instead of creating a
    duplicate company profile on every re-run."""
    if _sessionmaker is None:
        return None
    async with _sessionmaker() as s:
        row = (await s.execute(select(Lead).where(
            Lead.workspace_id == workspace_id,
            Lead.organization_id == organization_id).limit(1))).scalar_one_or_none()
        return row.id if row else None


async def competitor_activity_timeline(workspace_id: str, organization_id: str,
                                       limit: int = 60) -> list[dict]:
    """Chronological monitoring activity, derived from data we already store.

    Monitoring has no separate event log, and adding one would duplicate state.
    Instead each snapshot is a completed scan and each change is a detection, so
    a truthful activity feed can be reconstructed from those two tables. This is
    what lets the UI answer 'is monitoring actually working?' rather than showing
    an empty change list.
    """
    if _sessionmaker is None:
        return []
    async with _sessionmaker() as s:
        snaps = (await s.execute(select(CompetitorSnapshot).where(
            CompetitorSnapshot.workspace_id == workspace_id,
            CompetitorSnapshot.organization_id == organization_id)
            .order_by(CompetitorSnapshot.created_at.asc()))).scalars().all()
        changes = (await s.execute(select(CompetitorChange).where(
            CompetitorChange.workspace_id == workspace_id,
            CompetitorChange.organization_id == organization_id))).scalars().all()

    events: list[dict] = []
    seen_urls: set[str] = set()
    for sn in snaps:
        first = sn.url not in seen_urls
        seen_urls.add(sn.url)
        events.append({
            "kind": "baseline_created" if first else "scan_completed",
            "competitor_name": sn.competitor_name,
            "url": sn.url,
            "at": str(sn.created_at),
            "detail": ("Baseline captured — future scans compare against this."
                       if first else "Page scanned and compared against the baseline."),
        })
    for ch in changes:
        events.append({
            "kind": "change_detected",
            "competitor_name": ch.competitor_name,
            "url": ch.url,
            "at": str(ch.created_at),
            "detail": ch.summary,
            "severity": ch.severity,
            "category": ch.category,
            "change_id": ch.id,
        })

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


OPPORTUNITY_STATUSES = ("new", "reviewing", "in_progress", "completed", "dismissed")


async def get_opportunity_states(workspace_id: str,
                                 organization_id: str) -> dict[str, dict]:
    """Lifecycle overlay for an organization's derived opportunities, keyed by
    opportunity_key. Returns {} when nothing has been actioned yet."""
    if _sessionmaker is None:
        return {}
    async with _sessionmaker() as s:
        rows = (await s.execute(select(OpportunityState).where(
            OpportunityState.workspace_id == workspace_id,
            OpportunityState.organization_id == organization_id))).scalars().all()
    return {r.opportunity_key: {"status": r.status, "owner": r.owner,
                                "updated_at": str(r.updated_at)} for r in rows}


async def set_opportunity_state(workspace_id: str, organization_id: str,
                                opportunity_key: str, *,
                                status: str | None = None,
                                owner: str | None = None) -> dict:
    """Upsert the lifecycle overlay for one derived opportunity."""
    if status is not None and status not in OPPORTUNITY_STATUSES:
        raise ValueError(f"invalid status '{status}'")
    async with _sessionmaker() as s:
        row = (await s.execute(select(OpportunityState).where(
            OpportunityState.workspace_id == workspace_id,
            OpportunityState.organization_id == organization_id,
            OpportunityState.opportunity_key == opportunity_key))).scalar_one_or_none()
        if row is None:
            row = OpportunityState(
                id=uuid.uuid4().hex[:32], workspace_id=workspace_id,
                organization_id=organization_id, opportunity_key=opportunity_key,
                status=status or "new", owner=owner)
            s.add(row)
        else:
            if status is not None:
                row.status = status
            if owner is not None:
                row.owner = owner or None
            row.updated_at = utcnow()
        await s.commit()
        return {"opportunity_key": opportunity_key, "status": row.status,
                "owner": row.owner}
