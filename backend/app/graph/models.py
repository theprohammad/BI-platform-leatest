"""SQLAlchemy rows for the ontology. Internal — may change; ontology.py and
the GraphStore API are the stable surfaces (rule 4).

Phase 1.5 hardening:
- UNIQUE constraints on every get-or-create target (C2: concurrency safety)
- Junction tables with real FKs replace JSON id-arrays as the source of truth
  (C3: reverse indexes + referential integrity). JSON columns remain as
  denormalized read caches, written only by the store in the same transaction.
- claims.status + claims.identity_hash (C4: identity, dedup, supersession)
"""
from sqlalchemy import (JSON, Float, ForeignKey, Index, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # content hash
    url: Mapped[str] = mapped_column(String(1000))
    canonical_url: Mapped[str] = mapped_column(String(1000), index=True)
    domain: Mapped[str] = mapped_column(String(300), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30), default="web")
    published_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retrieved_at: Mapped[str] = mapped_column(String(40), index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.5)
    visibility: Mapped[str] = mapped_column(String(20), default="workspace")


class EntityRow(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("workspace_id", "name_key",
                                       name="uq_entity_ws_namekey"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(30), default="other")
    name: Mapped[str] = mapped_column(String(400), index=True)
    name_key: Mapped[str] = mapped_column(String(400), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    merged_into: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EdgeRow(Base):
    __tablename__ = "edges"
    __table_args__ = (UniqueConstraint("workspace_id", "source_entity_id",
                                       "relation", "target_entity_id",
                                       name="uq_edge_triple"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    source_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    relation: Mapped[str] = mapped_column(String(60), index=True)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)  # read cache
    trust: Mapped[dict] = mapped_column(JSON, default=dict)
    as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("claims.id"), nullable=True)  # C5-B backing claim


class ClaimRow(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("identity_hash", name="uq_claim_identity"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    subject_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="fact", index=True)
    statement: Mapped[str] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(String(400), nullable=True)
    value_entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    predicate: Mapped[str | None] = mapped_column(String(80), nullable=True)
    topic: Mapped[str] = mapped_column(String(60), default="general", index=True)
    as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    identity_hash: Mapped[str] = mapped_column(String(64))            # C4 identity
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    #        active | unsupported | superseded   (C4: no sentinel overloading)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)    # read cache
    trust: Mapped[dict] = mapped_column(JSON, default=dict)
    superseded_by: Mapped[str | None] = mapped_column(
        ForeignKey("claims.id"), nullable=True)                       # real FK now
    source_type: Mapped[str] = mapped_column(String(30), default="web")
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


Index("ix_claims_subject_topic", ClaimRow.subject_entity_id, ClaimRow.topic)
Index("ix_claims_ws_created", ClaimRow.workspace_id, ClaimRow.created_at)
Index("ix_claims_run", ClaimRow.run_id)


class InsightRow(Base):
    __tablename__ = "insights"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="finding", index=True)
    title: Mapped[str] = mapped_column(String(400))
    body: Mapped[str] = mapped_column(Text)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)       # read cache
    trust: Mapped[dict] = mapped_column(JSON, default=dict)
    authored_by: Mapped[str] = mapped_column(String(60))
    debate_status: Mapped[str] = mapped_column(String(20), default="unreviewed")
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


Index("ix_insights_ws_org", InsightRow.workspace_id, InsightRow.organization_id)


# ---- C3: junction tables (source of truth for citation links) --------------

class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)


Index("ix_claim_evidence_evidence", ClaimEvidenceRow.evidence_id)


class InsightClaimRow(Base):
    __tablename__ = "insight_claim"
    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.id"), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), primary_key=True)


Index("ix_insight_claim_claim", InsightClaimRow.claim_id)


class EdgeEvidenceRow(Base):
    __tablename__ = "edge_evidence"
    edge_id: Mapped[str] = mapped_column(ForeignKey("edges.id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)


Index("ix_edge_evidence_evidence", EdgeEvidenceRow.evidence_id)


Index("ix_claims_subject_predicate", ClaimRow.subject_entity_id, ClaimRow.predicate)
Index("ix_entities_merged_into", EntityRow.merged_into)


class EvidenceChunkRow(Base):
    __tablename__ = "evidence_chunks"
    __table_args__ = (UniqueConstraint("evidence_id", "seq", name="uq_chunk_seq"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), index=True)
    seq: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # JSON portable storage; pgvector column swap is an ops migration (spec §12 F-debt)
    embed_model: Mapped[str | None] = mapped_column(String(60), nullable=True)


class ExtractionCacheRow(Base):
    __tablename__ = "extraction_cache"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    subject_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    topic: Mapped[str] = mapped_column(String(60), primary_key=True)
    extraction_version: Mapped[str] = mapped_column(String(10), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40))


class EntityAliasRow(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("workspace_id", "alias_key", name="uq_alias"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    alias_key: Mapped[str] = mapped_column(String(400), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)


class EntityMergeLogRow(Base):
    __tablename__ = "entity_merge_log"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    loser_id: Mapped[str] = mapped_column(String(32), index=True)
    winner_id: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(30))   # exact|alias|auto|adjudicated|manual
    at: Mapped[str] = mapped_column(String(40))


class EntityMergeCandidateRow(Base):
    __tablename__ = "entity_merge_candidates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    a_id: Mapped[str] = mapped_column(String(32))
    b_id: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|merged|rejected


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default="run")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class EventRow(Base):
    __tablename__ = "events"
    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[str] = mapped_column(String(40))


class MonitoringConfigRow(Base):
    __tablename__ = "monitoring_config"
    organization_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    cadence: Mapped[str] = mapped_column(String(20), default="weekly")
    budget: Mapped[dict] = mapped_column(JSON, default=dict)


class ClaimTransitionRow(Base):
    """Lineage of record (Phase 2.5). Append-only, RETENTION-EXEMPT — never
    pruned; superseded_by on claims is only a mutable current-successor cache."""
    __tablename__ = "claim_transitions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    counterpart_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(String(40), default="")
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    at: Mapped[str] = mapped_column(String(40))
