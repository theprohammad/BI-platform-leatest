"""Graph tools — the ONLY read/write path to the Intelligence Graph for every
consumer (chat, agents, API, future surfaces). Names and inputs are stable."""
from pydantic import BaseModel, Field

from app.graph.ontology import (Claim, ClaimKind, Edge, EntityType, Evidence,
                                Insight, InsightKind, SourceType, TrustVector)
from app.graph.trust import domain_of, source_quality
from app.tools.registry import Tool, ToolContext, registry


class SearchClaimsIn(BaseModel):
    query: str
    limit: int = 12


async def _search_claims(ctx: ToolContext, p: SearchClaimsIn):
    return await ctx.graph.search_claims(ctx.workspace_id, p.query, limit=p.limit)


class ClaimsIn(BaseModel):
    subject_entity_id: str | None = None
    topic: str | None = None
    kind: str | None = None
    limit: int = 200


async def _claims(ctx: ToolContext, p: ClaimsIn):
    return await ctx.graph.claims(ctx.workspace_id, subject_entity_id=p.subject_entity_id,
                                  topic=p.topic, kind=p.kind, limit=p.limit)


class EvidenceIn(BaseModel):
    evidence_ids: list[str]


async def _evidence(ctx: ToolContext, p: EvidenceIn):
    return await ctx.graph.get_evidence(p.evidence_ids)


class TimelineIn(BaseModel):
    subject_entity_id: str


async def _timeline(ctx: ToolContext, p: TimelineIn):
    events = await ctx.graph.claims(ctx.workspace_id,
                                    subject_entity_id=p.subject_entity_id, kind="event")
    return sorted(events, key=lambda c: c.as_of or c.created_at)


class CoverageIn(BaseModel):
    subject_entity_id: str


async def _coverage(ctx: ToolContext, p: CoverageIn):
    # P1 (approved): quality vector per topic, not volume counts.
    return await ctx.graph.coverage_quality(ctx.workspace_id, p.subject_entity_id)


class EdgesIn(BaseModel):
    entity_id: str
    relation: str | None = None


async def _edges(ctx: ToolContext, p: EdgesIn):
    return await ctx.graph.edges_from(p.entity_id, relation=p.relation)


class WriteInsightIn(BaseModel):
    kind: InsightKind = InsightKind.FINDING
    title: str
    body: str
    claim_ids: list[str] = Field(min_length=1)
    authored_by: str
    trust: TrustVector = Field(default_factory=TrustVector)


async def _write_insight(ctx: ToolContext, p: WriteInsightIn):
    insight = Insight(id="", workspace_id=ctx.workspace_id,
                      organization_id=ctx.organization_id or "",
                      kind=p.kind, title=p.title, body=p.body,
                      claim_ids=p.claim_ids, trust=p.trust,
                      authored_by=p.authored_by, run_id=ctx.run_id)
    return await ctx.graph.add_insight(insight)


class WriteClaimIn(BaseModel):
    subject_entity_id: str
    statement: str
    kind: ClaimKind = ClaimKind.FACT
    topic: str = "general"
    value: str | None = None
    value_entity_id: str | None = None  # entity-valued predicates (B9)
    predicate: str | None = None      # S2/S7 structural key (normalized snake_case)
    as_of: str | None = None
    evidence_ids: list[str] = Field(min_length=1)
    source_type: SourceType = SourceType.WEB


def _norm_predicate(p: str | None) -> str | None:
    if not p:
        return None
    return "_".join(str(p).lower().strip().split())[:80]


async def _require_ws_entity(ctx: ToolContext, entity_id: str):
    """Phase 2.5 (A5): entity-referencing writes are tenant-validated AND
    merge tombstones are chased — callers holding a pre-merge id write to the
    winner, never the corpse (same rule reads already follow)."""
    ent = await ctx.graph.get_entity(entity_id)
    for _hop in range(10):
        if ent is None or not getattr(ent, "merged_into", None):
            break
        ent = await ctx.graph.get_entity(ent.merged_into)
    if ent is None or ent.workspace_id != ctx.workspace_id:
        raise ValueError(f"entity {entity_id} does not exist in this workspace")
    return ent


async def _write_claim(ctx: ToolContext, p: WriteClaimIn):
    subject = await _require_ws_entity(ctx, p.subject_entity_id)
    value_ent = (await _require_ws_entity(ctx, p.value_entity_id)
                 if p.value_entity_id else None)
    # Trust is computed by the store (single computation site — C1).
    claim = Claim(id="", workspace_id=ctx.workspace_id,
                  subject_entity_id=subject.id, kind=p.kind,
                  statement=p.statement, value=p.value,
                  value_entity_id=value_ent.id if value_ent else None,
                  predicate=_norm_predicate(p.predicate), topic=p.topic,
                  as_of=p.as_of, evidence_ids=p.evidence_ids,
                  source_type=p.source_type, run_id=ctx.run_id)
    result = await ctx.graph.add_claim_full(claim)
    # S7: structural conflict detection — ACTIVE claims only (lifecycle rule)
    if result.status == "active":
        try:
            from app.graph import diff
            await diff.detect_and_apply(ctx, result.claim_id)
        except Exception:
            pass
    return result.claim_id


class IngestEvidenceIn(BaseModel):
    url: str
    title: str = ""
    content: str = Field(min_length=1)
    published_date: str | None = None
    source_type: SourceType = SourceType.WEB


async def _ingest_evidence(ctx: ToolContext, p: IngestEvidenceIn):
    domain = domain_of(p.url)
    ev = Evidence(id="", url=p.url, canonical_url=p.url.rstrip("/"), domain=domain,
                  title=p.title, content=p.content, source_type=p.source_type,
                  published_date=p.published_date,
                  quality_score=source_quality(domain))
    ev_id, created = await ctx.graph.ingest_evidence(ev)
    if created:
        # S3: chunk + embed. Inline (hashing/local models are fast);
        # TODO(perf): move to an S6 background job when fastembed is enabled
        # at scale — internal change only, per decision policy.
        from app.research.chunker import chunk_text
        chunks = chunk_text(p.content)
        embedder = ctx.embedding()
        embeddings = embedder.embed(chunks) if chunks else []
        await ctx.graph.store_chunks(ev_id, chunks, embeddings, embedder.model_id)
    return {"evidence_id": ev_id, "created": created}


class ResolveEntityIn(BaseModel):
    name: str = Field(min_length=1)
    type: EntityType = EntityType.OTHER


async def _resolve_entity(ctx: ToolContext, p: ResolveEntityIn):
    # S4: layered resolution (exact → alias → fuzzy → banded decision).
    return await ctx.entity_resolver().resolve(ctx, p.name, p.type)


class WriteEdgeIn(BaseModel):
    source_entity_id: str
    relation: str = Field(min_length=1)
    target_entity_id: str
    evidence_ids: list[str] = Field(min_length=1)
    as_of: str | None = None


async def _write_edge(ctx: ToolContext, p: WriteEdgeIn):
    """C5-B (frozen invariant): the edge is a structural projection of a
    relational Claim. Phase 2.5: the backing claim goes through the
    graph.write_claim TOOL — one door for claims means one lifecycle,
    including relational facts (closes the A1-bis bypass). Endpoints are
    tenant-validated (A5)."""
    src = await _require_ws_entity(ctx, p.source_entity_id)
    tgt = await _require_ws_entity(ctx, p.target_entity_id)
    relation = _norm_predicate(p.relation)
    topic = "competitors" if relation == "competitor_of" else "profile"
    claim_id = await registry.invoke(
        ctx, "graph.write_claim",
        subject_entity_id=src.id, kind=ClaimKind.FACT,
        statement=f"{src.name} {relation.replace('_', ' ')} {tgt.name}.",
        value=tgt.name, value_entity_id=tgt.id,   # canonical (B9)
        predicate=relation, topic=topic,
        as_of=p.as_of, evidence_ids=p.evidence_ids)
    edge = Edge(id="", workspace_id=ctx.workspace_id,
                source_entity_id=src.id, relation=relation,
                target_entity_id=tgt.id, evidence_ids=p.evidence_ids,
                as_of=p.as_of, claim_id=claim_id)
    return await ctx.graph.add_edge(edge)


class SetClaimStatusIn(BaseModel):
    claim_ids: list[str] = Field(min_length=1)
    status: str  # active | unsupported | superseded


async def _set_claim_status(ctx: ToolContext, p: SetClaimStatusIn):
    # A5: claims must belong to this workspace
    owned = await ctx.graph.get_claims(p.claim_ids, workspace_id=ctx.workspace_id)
    if len(owned) != len(set(p.claim_ids)):
        raise ValueError("claim ids must exist in this workspace")
    return {"updated": await ctx.graph.set_claim_status(p.claim_ids, p.status,
                                                        run_id=ctx.run_id)}


class InsightsIn(BaseModel):
    kind: str | None = None


async def _insights(ctx: ToolContext, p: InsightsIn):
    if not ctx.organization_id:
        return []
    return await ctx.graph.insights(ctx.workspace_id, ctx.organization_id, kind=p.kind)


class ClaimsForEvidenceIn(BaseModel):
    evidence_id: str


async def _claims_for_evidence(ctx: ToolContext, p: ClaimsForEvidenceIn):
    return await ctx.graph.claims_citing_evidence(p.evidence_id)


class ResolveDisputeIn(BaseModel):
    insight_id: str
    winner_claim_id: str | None = None    # None → defer
    rationale: str = ""


async def _resolve_dispute(ctx: ToolContext, p: ResolveDisputeIn):
    """Phase 3 Critic verdict application. Winner path: the loser is superseded
    (transition reason 'adjudicated'); the existing lifecycle hook auto-resolves
    the dispute. Defer path: dispute stays open, marked 'deferred' so the
    Critic skips it until new evidence reopens the question."""
    disputes = [i for i in await ctx.graph.insights(ctx.workspace_id,
                                                    ctx.organization_id or "",
                                                    kind="dispute")
                if i.id == p.insight_id]
    if not disputes:
        raise ValueError("unknown dispute in this workspace")
    dispute = disputes[0]
    if p.winner_claim_id is None:
        await ctx.graph.annotate_insight(p.insight_id, debate_status="deferred",
                                         rationale=p.rationale)
        return {"resolved": False, "deferred": True}
    if p.winner_claim_id not in dispute.claim_ids:
        raise ValueError("winner must be one of the disputed claims")
    losers = [c for c in dispute.claim_ids if c != p.winner_claim_id]
    for loser in losers:
        await ctx.graph.supersede_claim(loser, p.winner_claim_id,
                                        run_id=ctx.run_id, reason="adjudicated")
    await ctx.graph.annotate_insight(p.insight_id, rationale=p.rationale)
    return {"resolved": True, "deferred": False, "superseded": losers}


class ReviewInsightIn(BaseModel):
    insight_id: str
    verdict: str            # validated | rejected
    rationale: str = ""


async def _review_insight(ctx: ToolContext, p: ReviewInsightIn):
    if p.verdict not in ("validated", "rejected"):
        raise ValueError("verdict must be validated|rejected")
    owned = [i for i in await ctx.graph.insights(ctx.workspace_id,
                                                 ctx.organization_id or "")
             if i.id == p.insight_id]
    if not owned:
        raise ValueError("unknown insight in this workspace")
    await ctx.graph.annotate_insight(p.insight_id, debate_status=p.verdict,
                                     rationale=p.rationale)
    return {"insight_id": p.insight_id, "debate_status": p.verdict}


class InsightsForClaimIn(BaseModel):
    claim_id: str


async def _insights_for_claim(ctx: ToolContext, p: InsightsForClaimIn):
    return await ctx.graph.insights_citing_claim(p.claim_id)


for _t in [
    Tool("graph.search", "Keyword search over claims in the workspace graph.", SearchClaimsIn, _search_claims),
    Tool("graph.claims", "List claims filtered by subject/topic/kind.", ClaimsIn, _claims),
    Tool("graph.evidence", "Fetch evidence documents by id.", EvidenceIn, _evidence),
    Tool("graph.timeline", "Chronological events for an entity.", TimelineIn, _timeline),
    Tool("graph.coverage", "What the graph already knows about a subject, per topic.", CoverageIn, _coverage),
    Tool("graph.edges", "Typed relationships from an entity.", EdgesIn, _edges),
    Tool("graph.write_insight", "Persist an agent insight (must cite existing claims).", WriteInsightIn, _write_insight),
    Tool("graph.write_claim", "Persist an evidence-backed claim (identity-deduped).", WriteClaimIn, _write_claim),
    Tool("graph.ingest_evidence", "Add a document to the global evidence corpus (content-addressed).", IngestEvidenceIn, _ingest_evidence),
    Tool("graph.resolve_entity", "Get-or-create an entity by name (concurrency-safe).", ResolveEntityIn, _resolve_entity),
    Tool("graph.write_edge", "Persist an evidence-backed relationship (upsert on triple).", WriteEdgeIn, _write_edge),
    Tool("graph.set_claim_status", "Transition claim status (verification/lifecycle).", SetClaimStatusIn, _set_claim_status),
    Tool("graph.insights", "List insights for the context organization.", InsightsIn, _insights),
    Tool("graph.claims_for_evidence", "Reverse lookup: claims citing an evidence document.", ClaimsForEvidenceIn, _claims_for_evidence),
    Tool("graph.insights_for_claim", "Reverse lookup: insights citing a claim.", InsightsForClaimIn, _insights_for_claim),
    Tool("graph.resolve_dispute", "Apply a Critic verdict to an open dispute (supersede loser or defer).", ResolveDisputeIn, _resolve_dispute),
    Tool("graph.review_insight", "Record the Critic's debate verdict on an insight.", ReviewInsightIn, _review_insight),
]:
    registry.register(_t)
