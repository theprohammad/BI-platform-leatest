"""THE ONTOLOGY — frozen by owner decision (Phase 1, rule 6).

Exactly five domain objects: Evidence, Entity, Edge, Claim, Insight.
No new object types may be added without explicit owner approval.
TrustVector is a value object, not an ontology object.

These Pydantic models are the public shape used by the Tool Layer, the API,
and extraction. Storage rows (graph/models.py) map 1:1 but may change freely;
these interfaces must not (rule 4).
"""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrustVector(BaseModel):
    """Multi-dimensional trust (Blueprint §1 / owner directive 13).
    All dimensions 0..1. reasoning_quality is None until a Critic scores it
    (Phase 3); corroboration counts distinct supporting domains, normalized."""
    confidence: float = 0.0
    source_quality: float = 0.0
    evidence_count: int = 0
    freshness: float = 0.0
    corroboration: float = 0.0
    reasoning_quality: float | None = None


class SourceType(str, Enum):
    WEB = "web"
    USER = "user_attestation"
    MEASUREMENT = "measurement"   # e.g. Lighthouse (Phase A)
    DOCUMENT = "document"         # PDFs etc. (Phase E)


class Evidence(BaseModel):
    """A source document in the GLOBAL corpus (rule 7). Content-addressed:
    id == sha256(canonical content) — dedup is identity, not a job."""
    id: str
    url: str
    canonical_url: str
    domain: str
    title: str = ""
    content: str
    source_type: SourceType = SourceType.WEB
    published_date: str | None = None
    retrieved_at: str = Field(default_factory=utcnow_iso)
    quality_score: float = 0.5
    visibility: str = "workspace"  # future: private RAG scoping (Blueprint VII)


class EntityType(str, Enum):
    ORGANIZATION = "organization"
    PERSON = "person"
    PRODUCT = "product"           # incl. programs/degrees/services
    LOCATION = "location"
    TECHNOLOGY = "technology"
    METRIC = "metric"
    OTHER = "other"


class Entity(BaseModel):
    id: str
    workspace_id: str
    type: EntityType = EntityType.OTHER
    name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)


class Edge(BaseModel):
    """Typed, evidence-backed relationship between two entities."""
    id: str
    workspace_id: str
    source_entity_id: str
    relation: str                 # competitor_of | offers | located_in | ...
    target_entity_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    trust: TrustVector = Field(default_factory=TrustVector)
    as_of: str | None = None
    claim_id: str | None = None   # C5-B: the relational Claim this edge projects


class ClaimKind(str, Enum):
    FACT = "fact"
    EVENT = "event"               # timeline = claims where kind=event
    METRIC = "metric"


class Claim(BaseModel):
    """Atomic evidence-backed statement. evidence_ids ≥ 1 is a HARD invariant
    (rule 5 traceability): an unevidenced claim cannot exist in the graph."""
    id: str
    workspace_id: str
    subject_entity_id: str
    kind: ClaimKind = ClaimKind.FACT
    statement: str
    value: str | None = None
    value_entity_id: str | None = None  # entity-valued predicates: canonical id (B9)
    predicate: str | None = None  # normalized structural key (S2/S7); None = prose-only
    topic: str = "general"        # coverage bucket: profile|market|competitors|...
    as_of: str | None = None
    evidence_ids: list[str]
    trust: TrustVector = Field(default_factory=TrustVector)
    status: str = "active"        # active | unsupported | superseded (C4)
    superseded_by: str | None = None
    source_type: SourceType = SourceType.WEB
    run_id: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)

    @field_validator("evidence_ids")
    @classmethod
    def _must_have_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("A Claim must cite at least one Evidence id")
        return v


class InsightKind(str, Enum):
    FINDING = "finding"
    SIGNAL = "signal"
    RECOMMENDATION = "recommendation"
    DISPUTE = "dispute"


class Insight(BaseModel):
    """Agent-authored reasoning artifact. claim_ids ≥ 1 is a HARD invariant:
    Recommendation → Insight → Claims → Evidence, never a black box (rule 5)."""
    id: str
    workspace_id: str
    organization_id: str
    kind: InsightKind = InsightKind.FINDING
    title: str
    body: str
    claim_ids: list[str]
    trust: TrustVector = Field(default_factory=TrustVector)
    authored_by: str              # agent key
    debate_status: str = "unreviewed"   # unreviewed|validated|revised|disputed (Phase 3)
    run_id: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)

    @field_validator("claim_ids")
    @classmethod
    def _must_have_claims(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("An Insight must cite at least one Claim id")
        return v
