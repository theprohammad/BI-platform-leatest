"""Tenancy-aware persistence skeleton (Blueprint Part VII: teams absorb into
`workspace → members → organizations` designed NOW).

Phase 0 persists runs when DATABASE_URL is configured; the Intelligence Graph
tables arrive in Phase 1 on this same base. Single-user = a workspace of one.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Default Workspace")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Organization(Base):
    """The Digital Twin root object. Graph tables reference this in Phase 1."""
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    root_entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # C6: persisted at intake; read paths NEVER resolve-by-name (no mutation on GET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    request: Mapped[dict] = mapped_column(JSON)
    manifest: Mapped[dict] = mapped_column(JSON)      # rule 2: full version stamp
    costs: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebsiteAudit(Base):
    """A persisted website/SEO audit — each row is a real, timestamped snapshot.
    History enables change detection (Crayon) and SEO trend tracking (Semrush).
    All fields are measured from the actual crawl; nothing fabricated."""
    __tablename__ = "website_audits"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(500), index=True)
    ok: Mapped[bool] = mapped_column(default=True)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)     # evidence-derived
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)   # full measured signals
    issue_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CompetitorSnapshot(Base):
    """A point-in-time capture of a monitored competitor URL. Diffing two
    snapshots produces real change events (Crayon-class). All fields measured."""
    __tablename__ = "competitor_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    competitor_entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    competitor_name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(500), index=True)
    page_type: Mapped[str] = mapped_column(String(40), default="homepage")  # homepage|pricing|features|blog
    signals: Mapped[dict] = mapped_column(JSON, default=dict)  # measured page signals
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CompetitorChange(Base):
    """A detected change between two snapshots — the atomic unit of the
    competitor timeline. Severity + category derived from what actually changed."""
    __tablename__ = "competitor_changes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    competitor_name: Mapped[str] = mapped_column(String(300), index=True)
    url: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(40), index=True)  # pricing|messaging|tech|content|feature|release
    severity: Mapped[str] = mapped_column(String(20), default="medium")  # critical|high|medium|low
    summary: Mapped[str] = mapped_column(Text)
    before: Mapped[str | None] = mapped_column(Text, nullable=True)
    after: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(default=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---- Apollo / Sales Intelligence models ------------------------------------
class Lead(Base):
    """A discovered/enriched company lead. Enrichment is real (website analysis
    + connectors); contact emails are only stored when publicly found, never
    fabricated. Persisted per workspace; graph-linked via organization_id."""
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(String(300), index=True)
    domain: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    employee_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enrichment: Mapped[dict] = mapped_column(JSON, default=dict)   # real collected signals
    score: Mapped[int] = mapped_column(default=0)                  # 0-100, evidence-derived
    score_band: Mapped[str] = mapped_column(String(20), default="cold")
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    stage: Mapped[str] = mapped_column(String(40), default="discovered", index=True)
    source: Mapped[str] = mapped_column(String(40), default="discovery")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contact(Base):
    """A public contact for a lead. email_status makes verification explicit:
    'found' only when a real public email was collected; otherwise 'not_found'.
    Emails are NEVER fabricated."""
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    email_status: Mapped[str] = mapped_column(String(20), default="not_found")
    linkedin: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)  # provenance
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CrmNote(Base):
    __tablename__ = "crm_notes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CrmTask(Base):
    __tablename__ = "crm_tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    done: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CrmActivity(Base):
    """Append-only activity log (stage moves, emails generated, notes, tasks)."""
    __tablename__ = "crm_activities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))   # stage_change|note|task|email|enriched
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OpportunityState(Base):
    """User lifecycle decisions for a DERIVED opportunity.

    Opportunities themselves are computed from the Intelligence Graph and are
    deliberately not persisted — storing them would create a second source of
    truth. Only status/owner, which cannot be derived from evidence, live here.
    """
    __tablename__ = "opportunity_states"
    __table_args__ = (UniqueConstraint("workspace_id", "organization_id",
                                       "opportunity_key",
                                       name="uq_opportunity_state"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    opportunity_key: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
