"""IntelligenceGraph — the system of record (owner rule 3).

Phase 1.5 hardening contract:
- WRITE methods are called ONLY by Tool Layer handlers (app/tools/*) — enforced
  by an architectural conformance test. Consumers never import the store.
- Every get-or-create is concurrency-safe: UNIQUE constraint + insert-then-
  recover (portable upsert across SQLite/Postgres).
- Junction tables are the source of truth for citation links; JSON columns are
  read caches written in the same transaction. Reverse queries are O(index).
- Claims have identity: re-adding the same (workspace, subject, topic,
  normalized statement) merges evidence instead of duplicating (C4), so
  re-research is idempotent and coverage counts stay honest.
- Trust is computed HERE, deterministically, on every write/merge — the single
  computation site (C1).
"""
import hashlib
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dataclasses import dataclass
from datetime import datetime, timezone

from app.graph.models import (ClaimEvidenceRow, ClaimRow, ClaimTransitionRow,
                              EdgeEvidenceRow, EdgeRow, EntityAliasRow,
                              EntityMergeCandidateRow, EntityMergeLogRow,
                              EntityRow, EvidenceChunkRow, EvidenceRow,
                              ExtractionCacheRow, InsightClaimRow, InsightRow)
from app.graph.predicates import normalize_value
from app.graph.ontology import (Claim, Edge, Entity, EntityType, Evidence,
                                Insight, TrustVector)
from app.graph.trust import compute_trust, trust_at_read


def _eid() -> str:
    return uuid.uuid4().hex[:32]


def content_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _name_key(name: str) -> str:
    return " ".join(name.lower().replace(",", " ").split())


# Marker separating an insight's narrative body from its validation rationale.
# Stored (audit trail) but never shown inline — read paths split it out and the
# UI presents it under a business label. The legacy "[critic]" prefix is still
# parsed so intelligence collected by earlier builds is cleaned up too.
VALIDATION_MARKER = "\n\n[[validation]] "
_LEGACY_VALIDATION_MARKER = "\n\n[critic] "


def split_validation_note(body: str) -> tuple[str, str]:
    """Split a stored insight body into (public_body, validation_note).

    Executives must never see internal reviewer wording inline in a finding, but
    the rationale is genuinely useful as a labelled 'why we trust this' note, so
    it is returned separately rather than discarded. Handles both the current
    marker and the legacy one already persisted in existing databases.
    """
    if not body:
        return "", ""
    for marker in (VALIDATION_MARKER, _LEGACY_VALIDATION_MARKER):
        if marker in body:
            head, _, tail = body.partition(marker)
            return head.strip(), tail.strip()
    # Also tolerate a bare inline "[critic] " with single newlines / no newline.
    if "[critic]" in body:
        head, _, tail = body.partition("[critic]")
        return head.strip(), tail.strip()
    return body.strip(), ""


def claim_identity(workspace_id: str, subject_entity_id: str, topic: str,
                   statement: str, predicate: str | None = None,
                   value: str | None = None) -> str:
    """CLAIM_IDENTITY_VERSION=2 (Phase 2.5): predicated claims with a NON-NULL
    value are identified by proposition (ws|subject|predicate|normalized value)
    — order-independent, topic-free, statement-free. Prose or valueless-
    predicated claims (D2) keep statement identity."""
    if predicate and value not in (None, ""):
        key = f"{workspace_id}|{subject_entity_id}|{predicate}|{normalize_value(value)}"
    else:
        key = f"{workspace_id}|{subject_entity_id}|{topic}|{' '.join(statement.split()).lower()}"
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class AddClaimResult:
    claim_id: str
    created: bool = False
    status: str = "active"
    reactivated: bool = False   # unsupported→active (new-domain rule)
    resurrected: bool = False   # superseded→active (recency rule)
    stale: bool = False         # attached to a dead row; exclude from run outputs


def _recency_of(as_of: str | None, evidence: list, fallback: str | None) -> str | None:
    """Assertion recency: as_of, else max evidence published_date, else None
    (UNKNOWN — treated as stale by rule 6 of CLAIM_LIFECYCLE.md)."""
    if as_of:
        return as_of
    dates = [e.published_date for e in evidence if e.published_date]
    if dates:
        return max(dates)
    return fallback


class IntelligenceGraph:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    def _session_for_reads(self):
        """Sanctioned read-session access for graph-package peers (diff engine).
        Writes still go through store methods only (conformance-tested)."""
        return self._sm()

    # ================= Evidence (global corpus) ==========================
    async def ingest_evidence(self, ev: Evidence) -> tuple[str, bool]:
        """(evidence_id, created). Content-addressed; concurrency-safe."""
        ev_id = content_hash(ev.content)
        async with self._sm() as s:
            if await s.get(EvidenceRow, ev_id):
                return ev_id, False
            s.add(EvidenceRow(id=ev_id, url=ev.url, canonical_url=ev.canonical_url,
                              domain=ev.domain, title=ev.title, content=ev.content,
                              source_type=ev.source_type.value,
                              published_date=ev.published_date,
                              retrieved_at=ev.retrieved_at,
                              quality_score=ev.quality_score,
                              visibility=ev.visibility))
            try:
                await s.commit()
                return ev_id, True
            except IntegrityError:      # lost the race: row exists now
                await s.rollback()
                return ev_id, False

    async def get_evidence(self, ids: list[str]) -> list[Evidence]:
        async with self._sm() as s:
            rows = (await s.execute(select(EvidenceRow)
                                    .where(EvidenceRow.id.in_(ids)))).scalars().all()
            return [self._ev(r) for r in rows]

    # ================= Entities ==========================================
    async def resolve_entity(self, workspace_id: str, name: str,
                             type_: EntityType = EntityType.OTHER,
                             aliases: list[str] | None = None) -> Entity:
        """Get-or-create, concurrency-safe via UNIQUE(workspace, name_key).
        TODO(phase-2): real entity resolution (fuzzy/alias merge) with fixtures."""
        key = _name_key(name)
        for _ in range(3):              # insert-or-recover, race-tolerant
            async with self._sm() as s:
                row = await self._entity_by_key(s, workspace_id, key)
                if row is not None:
                    return self._ent(row)
                s.add(EntityRow(id=_eid(), workspace_id=workspace_id, type=type_.value,
                                name=name.strip(), name_key=key,
                                aliases=aliases or [], attributes={}))
                try:
                    await s.commit()
                except IntegrityError:  # lost the race: retry as read
                    await s.rollback()
                    continue
                row = await self._entity_by_key(s, workspace_id, key)
                return self._ent(row)
        raise RuntimeError(f"resolve_entity contention: {name}")

    async def _entity_by_key(self, s, workspace_id: str, key: str) -> EntityRow | None:
        row = (await s.execute(select(EntityRow).where(
            EntityRow.workspace_id == workspace_id,
            EntityRow.name_key == key))).scalar_one_or_none()
        if row is None:  # alias layer (S4)
            alias = (await s.execute(select(EntityAliasRow).where(
                EntityAliasRow.workspace_id == workspace_id,
                EntityAliasRow.alias_key == key))).scalar_one_or_none()
            if alias:
                row = await s.get(EntityRow, alias.entity_id)
        while row is not None and row.merged_into:   # tombstone chase
            row = await s.get(EntityRow, row.merged_into)
        return row

    async def get_entity(self, entity_id: str) -> Entity | None:
        """Merge tombstones are chased: any id — including pre-merge ids held
        by callers or agents — resolves to the surviving entity, matching the
        name-key read path. Raw tombstone rows remain session-accessible for
        the merge log / review UI."""
        async with self._sm() as s:
            row = await s.get(EntityRow, entity_id)
            for _hop in range(10):
                if row is None or not row.merged_into:
                    break
                row = await s.get(EntityRow, row.merged_into)
            return self._ent(row) if row else None

    # ================= Edges ==============================================
    async def add_edge(self, edge: Edge) -> str:
        """Upsert on (ws, source, relation, target); merges evidence links and
        recomputes trust from the union. Concurrency-safe. C5-B: callers (the
        write_edge tool) supply edge.claim_id of the backing relational claim."""
        async with self._sm() as s:
            row = await self._edge_by_triple(s, edge)
            if row is None:
                row = EdgeRow(id=_eid(), workspace_id=edge.workspace_id,
                              source_entity_id=edge.source_entity_id,
                              relation=edge.relation,
                              target_entity_id=edge.target_entity_id,
                              evidence_ids=[], trust={}, as_of=edge.as_of,
                              claim_id=edge.claim_id)
                s.add(row)
                try:
                    await s.commit()
                except IntegrityError:
                    await s.rollback()
                    row = await self._edge_by_triple(s, edge)
            await self._link_edge_evidence(s, row.id, edge.evidence_ids)
            merged = await self._edge_evidence_ids(s, row.id)
            evidence = await self.get_evidence(merged)
            values = {"evidence_ids": merged,
                      "trust": compute_trust(evidence).model_dump()}
            if edge.claim_id and not row.claim_id:
                values["claim_id"] = edge.claim_id
            await s.execute(update(EdgeRow).where(EdgeRow.id == row.id).values(**values))
            await s.commit()
            return row.id

    @staticmethod
    async def _edge_by_triple(s, edge: Edge) -> EdgeRow | None:
        return (await s.execute(select(EdgeRow).where(
            EdgeRow.workspace_id == edge.workspace_id,
            EdgeRow.source_entity_id == edge.source_entity_id,
            EdgeRow.relation == edge.relation,
            EdgeRow.target_entity_id == edge.target_entity_id))).scalar_one_or_none()

    @staticmethod
    async def _link_edge_evidence(s, edge_id: str, evidence_ids: list[str]) -> None:
        existing = {r for (r,) in (await s.execute(
            select(EdgeEvidenceRow.evidence_id)
            .where(EdgeEvidenceRow.edge_id == edge_id))).all()}
        for ev_id in evidence_ids:
            if ev_id not in existing:
                s.add(EdgeEvidenceRow(edge_id=edge_id, evidence_id=ev_id))

    @staticmethod
    async def _edge_evidence_ids(s, edge_id: str) -> list[str]:
        return [r for (r,) in (await s.execute(
            select(EdgeEvidenceRow.evidence_id)
            .where(EdgeEvidenceRow.edge_id == edge_id))).all()]

    async def edges_from(self, entity_id: str, relation: str | None = None) -> list[Edge]:
        """C5-B: an edge is visible only while its backing claim is active.
        Legacy edges (claim_id NULL, pre-M2) remain visible until backfilled."""
        async with self._sm() as s:
            q = (select(EdgeRow)
                 .outerjoin(ClaimRow, ClaimRow.id == EdgeRow.claim_id)
                 .where(EdgeRow.source_entity_id == entity_id,
                        (EdgeRow.claim_id.is_(None)) | (ClaimRow.status == "active")))
            if relation:
                q = q.where(EdgeRow.relation == relation)
            return [self._edge(r) for r in (await s.execute(q)).scalars().all()]

    async def competitor_edges_for_org(self, workspace_id: str, root_entity_id: str,
                                       org_name: str) -> list[Edge]:
        """Resilient competitor lookup. Normally competitor_of edges hang off the
        org's root entity, but the extractor occasionally resolves the org's name
        to a near-duplicate entity (e.g. 'Acme' vs 'Acme University'), so those
        edges would otherwise be invisible on the competitors page. This gathers
        competitor_of edges from the root PLUS any same-named org entity, keeping
        the newest edge per target. Purely additive; never fabricates."""
        key = _name_key(org_name)
        async with self._sm() as s:
            # candidate source entities: the root, plus name/alias matches
            source_ids: set[str] = {root_entity_id}
            named = (await s.execute(select(EntityRow).where(
                EntityRow.workspace_id == workspace_id,
                EntityRow.name_key == key))).scalars().all()
            source_ids.update(e.id for e in named if not e.merged_into)
            alias_rows = (await s.execute(select(EntityAliasRow).where(
                EntityAliasRow.workspace_id == workspace_id,
                EntityAliasRow.alias_key == key))).scalars().all()
            source_ids.update(a.entity_id for a in alias_rows)

            q = (select(EdgeRow)
                 .outerjoin(ClaimRow, ClaimRow.id == EdgeRow.claim_id)
                 .where(EdgeRow.source_entity_id.in_(source_ids),
                        EdgeRow.relation == "competitor_of",
                        (EdgeRow.claim_id.is_(None)) | (ClaimRow.status == "active")))
            rows = (await s.execute(q)).scalars().all()
        # de-dupe by target, keep first (edges already active)
        by_target: dict[str, Edge] = {}
        for r in rows:
            edge = self._edge(r)
            by_target.setdefault(edge.target_entity_id, edge)
        return list(by_target.values())

    # ================= Claims ==============================================
    async def add_claim(self, claim: Claim) -> str:
        return (await self.add_claim_full(claim)).claim_id

    async def add_claim_full(self, claim: Claim) -> AddClaimResult:
        """Identity-upsert with the CLAIM_LIFECYCLE.md state machine:
        active→union · unsupported→reactivate on new domain · superseded→
        stale-attach or resurrect by recency. Trust computed here (C1)."""
        Claim.model_validate(claim.model_dump())          # evidence_ids ≥ 1
        identity = claim_identity(claim.workspace_id, claim.subject_entity_id,
                                  claim.topic, claim.statement,
                                  claim.predicate, claim.value)
        for _ in range(3):              # insert-or-merge, race-tolerant
            result = await self._add_claim_once(claim, identity)
            if result is not None:
                return result
        raise RuntimeError("add_claim contention")

    async def _add_claim_once(self, claim: Claim, identity: str) -> AddClaimResult | None:
        async with self._sm() as s:
            row = await self._claim_by_identity(s, identity)
            if row is None:
                evidence = await self.get_evidence(claim.evidence_ids)
                if len(evidence) != len(set(claim.evidence_ids)):
                    raise ValueError("Claim cites evidence ids that do not exist")
                row = ClaimRow(id=_eid(), workspace_id=claim.workspace_id,
                               subject_entity_id=claim.subject_entity_id,
                               kind=claim.kind.value, statement=claim.statement,
                               value=claim.value,
                               value_entity_id=claim.value_entity_id,
                               predicate=claim.predicate,
                               topic=claim.topic,
                               as_of=claim.as_of, identity_hash=identity,
                               status="active",
                               evidence_ids=list(dict.fromkeys(claim.evidence_ids)),
                               trust=compute_trust(evidence).model_dump(),
                               superseded_by=None,
                               source_type=claim.source_type.value,
                               run_id=claim.run_id, created_at=claim.created_at)
                s.add(row)
                try:
                    await s.flush()          # parent before junction FKs
                    for ev_id in dict.fromkeys(claim.evidence_ids):
                        s.add(ClaimEvidenceRow(claim_id=row.id, evidence_id=ev_id))
                    await s.commit()
                    return AddClaimResult(claim_id=row.id, created=True)
                except IntegrityError as exc:
                    await s.rollback()
                    if "identity" in str(exc.orig).lower() or "unique" in str(exc.orig).lower():
                        return None          # identity race: retry → merge path
                    raise ValueError(f"claim insert failed: {exc.orig}") from exc
            # merge path — STATUS-AWARE (CLAIM_LIFECYCLE.md rules 2/5/6/7);
            # race-tolerant: junction PK collision → rollback → retry loop
            try:
                existing = {r for (r,) in (await s.execute(
                    select(ClaimEvidenceRow.evidence_id)
                    .where(ClaimEvidenceRow.claim_id == row.id))).all()}
                new_ids = [e for e in dict.fromkeys(claim.evidence_ids)
                           if e not in existing]
                result = AddClaimResult(claim_id=row.id, status=row.status)

                if row.status == "active" and claim.as_of and (
                        row.as_of is None or claim.as_of > row.as_of):
                    row.as_of = claim.as_of        # currency advances on merge

                if row.status == "superseded":
                    incoming_ev = await self.get_evidence(list(claim.evidence_ids))
                    incoming = _recency_of(claim.as_of, incoming_ev, None)
                    # chase the chain: the gate is the TERMINAL successor (the
                    # current incumbent), not the direct one — a re-assertion
                    # newer than a middle link but older than the incumbent is
                    # still stale (rule 6/7, CLAIM_LIFECYCLE.md)
                    successor, next_id = None, row.superseded_by
                    for _hop in range(10):
                        if not next_id:
                            break
                        successor = await s.get(ClaimRow, next_id)
                        if successor is None:
                            break
                        next_id = successor.superseded_by
                    succ_recency = (successor.as_of or successor.created_at) if successor else ""
                    if incoming is not None and incoming > succ_recency:
                        # rule 7: RESURRECTION — value returned, newer than successor
                        row.status = "active"
                        row.as_of = incoming       # currency = the re-assertion date
                        displaced = row.superseded_by
                        row.superseded_by = None
                        result.status, result.resurrected = "active", True
                        s.add(ClaimTransitionRow(claim_id=row.id,
                                                 from_status="superseded",
                                                 to_status="active",
                                                 counterpart_id=displaced,
                                                 reason="resurrected",
                                                 run_id=claim.run_id,
                                                 at=datetime.now(timezone.utc).isoformat()))
                    else:
                        # rule 6: stale re-assertion — attach for lineage only
                        result.stale = True

                elif row.status == "unsupported":
                    linked = await self.get_evidence(list(existing))
                    linked_domains = {e.domain for e in linked}
                    incoming_ev = await self.get_evidence(new_ids)
                    if any(e.domain not in linked_domains for e in incoming_ev):
                        # rule 5: REACTIVATION on a genuinely new domain (D3)
                        row.status = "active"
                        result.status, result.reactivated = "active", True
                        s.add(ClaimTransitionRow(claim_id=row.id,
                                                 from_status="unsupported",
                                                 to_status="active",
                                                 counterpart_id=None,
                                                 reason="reactivated_new_domain",
                                                 run_id=claim.run_id,
                                                 at=datetime.now(timezone.utc).isoformat()))
                    else:
                        result.stale = True   # same-domain re-assertion: stay dead

                for ev_id in new_ids:
                    s.add(ClaimEvidenceRow(claim_id=row.id, evidence_id=ev_id))
                merged = list(existing) + new_ids
                evidence = await self.get_evidence(merged)
                await s.execute(update(ClaimRow).where(ClaimRow.id == row.id)
                                .values(evidence_ids=merged, status=row.status,
                                        superseded_by=row.superseded_by,
                                        as_of=row.as_of,
                                        trust=compute_trust(evidence).model_dump()))
                await s.commit()
                return result
            except IntegrityError:
                await s.rollback()
                return None

    @staticmethod
    async def _claim_by_identity(s, identity: str) -> ClaimRow | None:
        return (await s.execute(select(ClaimRow).where(
            ClaimRow.identity_hash == identity))).scalar_one_or_none()

    async def set_claim_status(self, claim_ids: list[str], status: str,
                               run_id: str | None = None) -> int:
        """Lifecycle transitions. Never deletes. Logs claim_transitions and
        auto-resolves open disputes on any exit from `active` (D3)."""
        if status not in ("active", "unsupported", "superseded"):
            raise ValueError(f"invalid claim status: {status}")
        now = datetime.now(timezone.utc).isoformat()
        async with self._sm() as s:
            rows = (await s.execute(select(ClaimRow)
                                    .where(ClaimRow.id.in_(claim_ids)))).scalars().all()
            for row in rows:
                if row.status == status:
                    continue
                s.add(ClaimTransitionRow(claim_id=row.id, from_status=row.status,
                                         to_status=status, counterpart_id=None,
                                         reason="set_status", run_id=run_id, at=now))
                if row.status == "active":
                    await self._resolve_open_disputes(s, row.id)
                row.status = status
                if status != "superseded":
                    row.superseded_by = None
            await s.commit()
            return len(rows)

    async def annotate_insight(self, insight_id: str, *,
                               debate_status: str | None = None,
                               rationale: str = "") -> None:
        """Validation verdicts. The rationale is appended to the body behind a
        machine-readable marker so the insight stays one auditable artifact, and
        so read paths can split it out and present it as a labelled
        'Validation review' instead of leaking internal wording into prose."""
        async with self._sm() as s:
            row = await s.get(InsightRow, insight_id)
            if row is None:
                return
            if debate_status:
                row.debate_status = debate_status
            if rationale:
                row.body = f"{row.body}{VALIDATION_MARKER}{rationale}"
            await s.commit()

    async def supersede_claim(self, old_id: str, new_id: str,
                              run_id: str | None = None,
                              reason: str = "conflict_lost") -> None:
        """Lineage-preserving replacement. superseded_by = mutable current-
        successor cache; the transition row is the record (CLAIM_LIFECYCLE.md).
        Concurrency-safe: the status flip is a CONDITIONAL update; only the
        winner of the race logs the transition, so history stays single-rowed
        under simultaneous adjudication of the same claim."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._sm() as s:
            row = await s.get(ClaimRow, old_id)
            if row is None or row.status == "superseded":
                return
            from_status = row.status
            # atomic claim: flip to superseded only if still in from_status
            won = (await s.execute(
                update(ClaimRow)
                .where(ClaimRow.id == old_id, ClaimRow.status == from_status)
                .values(status="superseded", superseded_by=new_id))).rowcount
            if not won:
                await s.rollback()      # another writer already superseded it
                return
            s.add(ClaimTransitionRow(claim_id=old_id, from_status=from_status,
                                     to_status="superseded", counterpart_id=new_id,
                                     reason=reason, run_id=run_id, at=now))
            if from_status == "active":
                await self._resolve_open_disputes(s, old_id)
            await s.commit()

    @staticmethod
    async def _resolve_open_disputes(s, claim_id: str) -> None:
        """A claim leaving `active`: (D3) resolves every open dispute citing it,
        and (Phase 3) flags every other insight citing it as STALE so debate-
        validated conclusions don't outlive their premises."""
        dispute_ids = [i for (i,) in (await s.execute(
            select(InsightRow.id)
            .join(InsightClaimRow, InsightClaimRow.insight_id == InsightRow.id)
            .where(InsightClaimRow.claim_id == claim_id,
                   InsightRow.kind == "dispute",
                   InsightRow.debate_status != "resolved"))).all()]
        if dispute_ids:
            await s.execute(update(InsightRow)
                            .where(InsightRow.id.in_(dispute_ids))
                            .values(debate_status="resolved"))
        stale_ids = [i for (i,) in (await s.execute(
            select(InsightRow.id)
            .join(InsightClaimRow, InsightClaimRow.insight_id == InsightRow.id)
            .where(InsightClaimRow.claim_id == claim_id,
                   InsightRow.kind != "dispute",
                   InsightRow.debate_status.notin_(("stale", "rejected"))))).all()]
        if stale_ids:
            await s.execute(update(InsightRow)
                            .where(InsightRow.id.in_(stale_ids))
                            .values(debate_status="stale"))

    async def transitions_for(self, claim_id: str) -> list[dict]:
        async with self._sm() as s:
            rows = (await s.execute(select(ClaimTransitionRow)
                                    .where(ClaimTransitionRow.claim_id == claim_id)
                                    .order_by(ClaimTransitionRow.id))).scalars().all()
            return [{"from": r.from_status, "to": r.to_status,
                     "counterpart": r.counterpart_id, "reason": r.reason,
                     "run_id": r.run_id, "at": r.at} for r in rows]

    async def claims(self, workspace_id: str, *, subject_entity_id: str | None = None,
                     topic: str | None = None, kind: str | None = None,
                     status: str = "active", limit: int = 200) -> list[Claim]:
        async with self._sm() as s:
            q = select(ClaimRow).where(ClaimRow.workspace_id == workspace_id)
            if subject_entity_id:
                q = q.where(ClaimRow.subject_entity_id == subject_entity_id)
            if topic:
                q = q.where(ClaimRow.topic == topic)
            if kind:
                q = q.where(ClaimRow.kind == kind)
            if status != "any":
                q = q.where(ClaimRow.status == status)
            return [self._claim(r) for r in (await s.execute(q.limit(limit))).scalars().all()]

    async def get_claims(self, ids: list[str],
                         workspace_id: str | None = None) -> list[Claim]:
        """workspace_id, when provided, scopes the read (authz seam — B7)."""
        async with self._sm() as s:
            q = select(ClaimRow).where(ClaimRow.id.in_(ids))
            if workspace_id:
                q = q.where(ClaimRow.workspace_id == workspace_id)
            return [self._claim(r) for r in (await s.execute(q)).scalars().all()]

    # ---- reverse queries (C3: monitoring & staleness primitives) ---------
    async def claims_citing_evidence(self, evidence_id: str) -> list[Claim]:
        async with self._sm() as s:
            q = (select(ClaimRow)
                 .join(ClaimEvidenceRow, ClaimEvidenceRow.claim_id == ClaimRow.id)
                 .where(ClaimEvidenceRow.evidence_id == evidence_id))
            return [self._claim(r) for r in (await s.execute(q)).scalars().all()]

    async def insights_citing_claim(self, claim_id: str) -> list[Insight]:
        async with self._sm() as s:
            q = (select(InsightRow)
                 .join(InsightClaimRow, InsightClaimRow.insight_id == InsightRow.id)
                 .where(InsightClaimRow.claim_id == claim_id))
            return [self._insight(r) for r in (await s.execute(q)).scalars().all()]

    async def coverage(self, workspace_id: str, subject_entity_id: str) -> dict:
        async with self._sm() as s:
            q = (select(ClaimRow.topic, func.count(), func.max(ClaimRow.created_at))
                 .where(ClaimRow.workspace_id == workspace_id,
                        ClaimRow.subject_entity_id == subject_entity_id,
                        ClaimRow.status == "active")
                 .group_by(ClaimRow.topic))
            return {t: {"claims": c, "newest": newest}
                    for t, c, newest in (await s.execute(q)).all()}

    # ================= Insights ============================================
    async def add_insight(self, insight: Insight) -> str:
        Insight.model_validate(insight.model_dump())      # claim_ids ≥ 1
        claim_ids = list(dict.fromkeys(insight.claim_ids))
        existing = await self.get_claims(claim_ids, workspace_id=insight.workspace_id)
        if len(existing) != len(claim_ids):
            raise ValueError("Insight cites claim ids that do not exist in this workspace")
        async with self._sm() as s:
            row = InsightRow(id=_eid(), workspace_id=insight.workspace_id,
                             organization_id=insight.organization_id,
                             kind=insight.kind.value, title=insight.title,
                             body=insight.body, claim_ids=claim_ids,
                             trust=insight.trust.model_dump(),
                             authored_by=insight.authored_by,
                             debate_status=insight.debate_status,
                             run_id=insight.run_id, created_at=insight.created_at)
            s.add(row)
            await s.flush()                  # parent before junction FKs
            for cid in claim_ids:
                s.add(InsightClaimRow(insight_id=row.id, claim_id=cid))
            await s.commit()
            return row.id

    async def insights(self, workspace_id: str, organization_id: str,
                       kind: str | None = None) -> list[Insight]:
        async with self._sm() as s:
            q = select(InsightRow).where(InsightRow.workspace_id == workspace_id,
                                         InsightRow.organization_id == organization_id)
            if kind:
                q = q.where(InsightRow.kind == kind)
            return [self._insight(r) for r in (await s.execute(q)).scalars().all()]

    # ================= Workspace read surface (product; read-only) ==========
    async def insight_detail(self, insight_id: str,
                             workspace_id: str | None = None) -> dict | None:
        """One insight with its cited claims fully expanded (for the explorer).
        Scoped to workspace when provided (product endpoints always provide it)."""
        async with self._sm() as s:
            row = await s.get(InsightRow, insight_id)
            if row is None or (workspace_id and row.workspace_id != workspace_id):
                return None
            insight = self._insight(row)
        claims = await self.get_claims(insight.claim_ids)
        return {"insight": insight.model_dump(),
                "claims": [c.model_dump() for c in claims]}

    async def recommendation_chain(self, workspace_id: str, organization_id: str,
                                   insight_id: str) -> dict | None:
        """Full evidence chain: recommendation → insights → claims → evidence.
        A recommendation cites claims directly; supporting insights are the
        other insights that cite any of those same claims (shared-claim join)."""
        async with self._sm() as s:
            rec_row = await s.get(InsightRow, insight_id)
            if (rec_row is None or rec_row.workspace_id != workspace_id
                    or rec_row.organization_id != organization_id):
                return None
            rec = self._insight(rec_row)
        claims = await self.get_claims(rec.claim_ids)
        # supporting insights: any non-dispute insight sharing a cited claim
        supporting: dict[str, dict] = {}
        for claim in claims:
            for ins in await self.insights_citing_claim(claim.id):
                if ins.id != insight_id and ins.kind.value != "dispute":
                    supporting[ins.id] = ins.model_dump()
        # claims → evidence
        claim_blocks = []
        for claim in claims:
            evidence = await self.get_evidence(claim.evidence_ids)
            claim_blocks.append({"claim": claim.model_dump(),
                                 "evidence": [e.model_dump() for e in evidence]})
        return {"recommendation": rec.model_dump(),
                "supporting_insights": list(supporting.values()),
                "claims": claim_blocks}

    async def dispute_detail(self, workspace_id: str, organization_id: str,
                             insight_id: str) -> dict | None:
        async with self._sm() as s:
            row = await s.get(InsightRow, insight_id)
            if (row is None or row.kind != "dispute"
                    or row.workspace_id != workspace_id
                    or row.organization_id != organization_id):
                return None
            dispute = self._insight(row)
        claims = await self.get_claims(dispute.claim_ids)
        sides = []
        for claim in claims:
            evidence = await self.get_evidence(claim.evidence_ids)
            sides.append({"claim": claim.model_dump(),
                          "evidence": [e.model_dump() for e in evidence]})
        winner_id = None
        for claim in claims:                     # the surviving/active one, if resolved
            if claim.status == "active" and dispute.debate_status == "resolved":
                winner_id = claim.id
        return {"dispute": dispute.model_dump(), "sides": sides,
                "status": dispute.debate_status, "winner_claim_id": winner_id}

    async def workspace_search(self, workspace_id: str, organization_id: str,
                               query: str, limit: int = 10) -> dict:
        """Global search across entities, claims, insights (+recommendations)."""
        q = query.strip().lower()
        entities = [e for e in await self.list_entities(workspace_id)
                    if q in e.name.lower()
                    or any(q in a.lower() for a in e.aliases)][:limit]
        claims = await self.search_claims(workspace_id, query, limit)
        insights_all = await self.insights(workspace_id, organization_id)
        matched_insights, matched_recs = [], []
        for i in insights_all:
            if q in i.title.lower() or q in i.body.lower():
                (matched_recs if i.kind.value == "recommendation"
                 else matched_insights).append(i.model_dump())
        return {"entities": [e.model_dump() for e in entities],
                "claims": [c.model_dump() for c in claims],
                "insights": matched_insights[:limit],
                "recommendations": matched_recs[:limit]}

    # ================= Retrieval (S5) ======================================
    async def search_claims(self, workspace_id: str, query: str, limit: int = 12) -> list[Claim]:
        """STABLE signature (rule 4). Strategy dispatch: hybrid (S5) or the
        keyword baseline (kept runnable for A/B + rollback flag)."""
        from app.core.config import get_settings
        if get_settings().retrieval_strategy == "hybrid":
            from app.graph.retrieval import HybridRetriever
            if not hasattr(self, "_retriever"):
                self._retriever = HybridRetriever(self)
            return await self._retriever.search(workspace_id, query, limit)
        return await self.keyword_search_claims(workspace_id, query, limit)

    async def keyword_search_claims(self, workspace_id: str, query: str, limit: int = 12) -> list[Claim]:
        """Keyword baseline / FTS leg on SQLite."""
        terms = [t for t in query.lower().split() if len(t) > 2][:8]
        if not terms:
            return []
        async with self._sm() as s:
            conds = [func.lower(ClaimRow.statement).like(f"%{t}%") for t in terms]
            rows = (await s.execute(
                select(ClaimRow).where(ClaimRow.workspace_id == workspace_id,
                                       ClaimRow.status == "active", or_(*conds))
                .limit(limit * 3))).scalars().all()
        mapped = [self._claim(r) for r in rows]      # read-time trust (B-item 11)
        scored = sorted(
            ((sum(c.statement.lower().count(t) for t in terms)
              + c.trust.confidence, c) for c in mapped),
            key=lambda x: -x[0])
        return [c for _, c in scored[:limit]]


    # ================= Phase 2: quality coverage (S1) ======================
    async def coverage_quality(self, workspace_id: str, subject_entity_id: str) -> dict:
        """P1: per-topic knowledge QUALITY, not volume. The planner's and
        Monitoring's targeting function."""
        from datetime import datetime, timezone
        claims = await self.claims(workspace_id, subject_entity_id=subject_entity_id,
                                   status="any", limit=2000)
        # domains per topic via junctions
        async with self._sm() as s:
            rows = (await s.execute(
                select(ClaimRow.topic, EvidenceRow.domain)
                .join(ClaimEvidenceRow, ClaimEvidenceRow.claim_id == ClaimRow.id)
                .join(EvidenceRow, EvidenceRow.id == ClaimEvidenceRow.evidence_id)
                .where(ClaimRow.workspace_id == workspace_id,
                       ClaimRow.subject_entity_id == subject_entity_id))).all()
            dispute_rows = (await s.execute(
                select(ClaimRow.topic, func.count(func.distinct(InsightRow.id)))
                .join(InsightClaimRow, InsightClaimRow.claim_id == ClaimRow.id)
                .join(InsightRow, InsightRow.id == InsightClaimRow.insight_id)
                .where(ClaimRow.subject_entity_id == subject_entity_id,
                       InsightRow.kind == "dispute",
                       InsightRow.debate_status != "resolved")
                .group_by(ClaimRow.topic))).all()
        domains: dict[str, set] = {}
        for topic, domain in rows:
            domains.setdefault(topic, set()).add(domain)
        disputes = dict(dispute_rows)
        now = datetime.now(timezone.utc)
        out: dict[str, dict] = {}
        for c in claims:
            t = out.setdefault(c.topic, {"claims": 0, "active": 0, "unsupported": 0,
                                         "confidences": [], "newest": None})
            t["claims"] += 1
            if c.status == "active":
                t["active"] += 1
                t["confidences"].append(c.trust.confidence)
            elif c.status == "unsupported":
                t["unsupported"] += 1
            ref = c.as_of or c.created_at
            if t["newest"] is None or ref > t["newest"]:
                t["newest"] = ref
        result = {}
        for topic, t in out.items():
            try:
                newest_dt = datetime.fromisoformat(str(t["newest"]).replace("Z", "+00:00"))
                if newest_dt.tzinfo is None:
                    newest_dt = newest_dt.replace(tzinfo=timezone.utc)
                staleness = max(0.0, (now - newest_dt).days)
            except (ValueError, TypeError):
                staleness = 9999.0
            confs = t["confidences"]
            result[topic] = {
                "claims": t["active"],
                "mean_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
                "distinct_domains": len(domains.get(topic, set())),
                "domains": sorted(domains.get(topic, set()))[:8],
                "staleness_days": staleness,
                "unsupported_rate": round(t["unsupported"] / t["claims"], 3) if t["claims"] else 0.0,
                "open_disputes": int(disputes.get(topic, 0)),
                "newest_as_of": t["newest"],
            }
        return result

    # ================= Phase 2: conflicts (S7) ==============================
    async def find_conflicting_claims(self, workspace_id: str, subject_entity_id: str,
                                      predicate: str, exclude_id: str) -> list[Claim]:
        if not predicate:
            return []
        async with self._sm() as s:
            rows = (await s.execute(select(ClaimRow).where(
                ClaimRow.workspace_id == workspace_id,
                ClaimRow.subject_entity_id == subject_entity_id,
                ClaimRow.predicate == predicate,
                ClaimRow.status == "active",
                ClaimRow.id != exclude_id))).scalars().all()
            return [self._claim(r) for r in rows]

    async def conflicting_value_groups(self, workspace_id: str,
                                       subject_entity_id: str) -> list[list[Claim]]:
        """B6 reconciliation: groups of ACTIVE claims sharing a functional
        predicate with >1 distinct normalized values (parallel-write blind
        spot). Diff engine sweeps these at run end."""
        from app.graph.predicates import classify
        async with self._sm() as s:
            rows = (await s.execute(select(ClaimRow).where(
                ClaimRow.workspace_id == workspace_id,
                ClaimRow.subject_entity_id == subject_entity_id,
                ClaimRow.status == "active",
                ClaimRow.predicate.is_not(None)))).scalars().all()
        groups: dict[str, list] = {}
        for r in rows:
            if r.value and classify(r.predicate) == "functional":
                groups.setdefault(r.predicate, []).append(self._claim(r))
        out = []
        for claims in groups.values():
            if len({normalize_value(c.value) for c in claims}) > 1:
                out.append(claims)
        return out

    async def claims_created_since(self, workspace_id: str, subject_entity_id: str,
                                   since_iso: str) -> list[Claim]:
        async with self._sm() as s:
            rows = (await s.execute(select(ClaimRow).where(
                ClaimRow.workspace_id == workspace_id,
                ClaimRow.subject_entity_id == subject_entity_id,
                ClaimRow.created_at >= since_iso)
                .order_by(ClaimRow.created_at))).scalars().all()
            return [self._claim(r) for r in rows]

    async def high_fanin_evidence(self, workspace_id: str, subject_entity_id: str,
                                  min_claims: int = 2, limit: int = 10) -> list[Evidence]:
        """S8 refresh targeting: evidence documents backing many active claims."""
        async with self._sm() as s:
            sub = (select(ClaimEvidenceRow.evidence_id,
                          func.count().label("fanin"))
                   .join(ClaimRow, ClaimRow.id == ClaimEvidenceRow.claim_id)
                   .where(ClaimRow.workspace_id == workspace_id,
                          ClaimRow.subject_entity_id == subject_entity_id,
                          ClaimRow.status == "active")
                   .group_by(ClaimEvidenceRow.evidence_id)
                   .having(func.count() >= min_claims)
                   .order_by(func.count().desc()).limit(limit)).subquery()
            rows = (await s.execute(select(EvidenceRow)
                                    .join(sub, sub.c.evidence_id == EvidenceRow.id))).scalars().all()
            return [self._ev(r) for r in rows]

    # ================= Phase 2: chunks & cache (S3) =========================
    async def store_chunks(self, evidence_id: str, chunks: list[str],
                           embeddings: list[list[float]] | None,
                           embed_model: str | None) -> int:
        async with self._sm() as s:
            existing = (await s.execute(select(func.count()).select_from(EvidenceChunkRow)
                                        .where(EvidenceChunkRow.evidence_id == evidence_id))).scalar()
            if existing:
                return 0     # content-addressed: chunks of the same evidence never change
            for i, text in enumerate(chunks):
                s.add(EvidenceChunkRow(id=_eid(), evidence_id=evidence_id, seq=i,
                                       text=text,
                                       embedding=(embeddings[i] if embeddings else None),
                                       embed_model=embed_model))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                return 0
            return len(chunks)

    async def chunks_with_embeddings(self, workspace_id: str, limit: int = 5000):
        """Vector-leg candidate pool. TODO(prod): pgvector HNSW SQL replaces
        this Python scan when dialect is postgresql (spec S5 / debt #4)."""
        async with self._sm() as s:
            rows = (await s.execute(select(EvidenceChunkRow)
                                    .where(EvidenceChunkRow.embedding.is_not(None))
                                    .limit(limit))).scalars().all()
            return [(r.evidence_id, r.text, r.embedding) for r in rows]

    async def extraction_cached(self, evidence_id: str, subject_entity_id: str,
                                topic: str, version: str) -> bool:
        async with self._sm() as s:
            row = await s.get(ExtractionCacheRow,
                              (evidence_id, subject_entity_id, topic, version))
            return row is not None

    async def mark_extracted(self, evidence_id: str, subject_entity_id: str,
                             topic: str, version: str) -> None:
        from datetime import datetime, timezone
        async with self._sm() as s:
            s.add(ExtractionCacheRow(evidence_id=evidence_id,
                                     subject_entity_id=subject_entity_id,
                                     topic=topic, extraction_version=version,
                                     created_at=datetime.now(timezone.utc).isoformat()))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()

    # ================= Phase 2: entity resolution & merge (S4) ==============
    async def list_entities(self, workspace_id: str, type_: str | None = None,
                            limit: int = 5000) -> list[Entity]:
        async with self._sm() as s:
            q = select(EntityRow).where(EntityRow.workspace_id == workspace_id,
                                        EntityRow.merged_into.is_(None))
            if type_:
                q = q.where(EntityRow.type == type_)
            return [self._ent(r) for r in (await s.execute(q.limit(limit))).scalars().all()]

    async def add_alias(self, workspace_id: str, entity_id: str, alias: str) -> None:
        async with self._sm() as s:
            s.add(EntityAliasRow(id=_eid(), workspace_id=workspace_id,
                                 alias_key=_name_key(alias), entity_id=entity_id))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()

    async def record_merge_candidate(self, workspace_id: str, a_id: str, b_id: str,
                                     score: float) -> None:
        async with self._sm() as s:
            s.add(EntityMergeCandidateRow(id=_eid(), workspace_id=workspace_id,
                                          a_id=min(a_id, b_id), b_id=max(a_id, b_id),
                                          score=score))
            await s.commit()

    async def merge_claims(self, s, loser_row: ClaimRow, winner_id: str,
                           run_id: str | None = None) -> None:
        """Fold one claim into another (evidence union + supersession lineage).
        Session-scoped; used by entity merge collisions and migration 0002."""
        now = datetime.now(timezone.utc).isoformat()
        have = {r for (r,) in (await s.execute(
            select(ClaimEvidenceRow.evidence_id)
            .where(ClaimEvidenceRow.claim_id == winner_id))).all()}
        ev_ids = [r for (r,) in (await s.execute(
            select(ClaimEvidenceRow.evidence_id)
            .where(ClaimEvidenceRow.claim_id == loser_row.id))).all()]
        for ev in ev_ids:
            if ev not in have:
                s.add(ClaimEvidenceRow(claim_id=winner_id, evidence_id=ev))
        s.add(ClaimTransitionRow(claim_id=loser_row.id, from_status=loser_row.status,
                                 to_status="superseded", counterpart_id=winner_id,
                                 reason="claim_merge", run_id=run_id, at=now))
        loser_row.status, loser_row.superseded_by = "superseded", winner_id

    async def merge_entities(self, workspace_id: str, loser_id: str, winner_id: str,
                             *, score: float, method: str) -> dict:
        """S4 merge: repoint claims (recomputing identity; colliding claims are
        claim-merged with lineage), repoint/merge edges, alias the loser,
        tombstone it, log it. Reversible via the log (unmerge is Phase W UI).
        Phase 2.5: workspace guard — both entities must belong to workspace_id."""
        if loser_id == winner_id:
            return {"merged": False}
        moved, collided = 0, 0
        loser = await self.get_entity(loser_id)
        winner = await self.get_entity(winner_id)
        if (loser is None or winner is None
                or loser.workspace_id != workspace_id
                or winner.workspace_id != workspace_id):
            raise ValueError("merge_entities: both entities must exist in the workspace")
        async with self._sm() as s:
            claim_rows = (await s.execute(select(ClaimRow).where(
                ClaimRow.subject_entity_id == loser_id))).scalars().all()
            for row in claim_rows:
                new_identity = claim_identity(row.workspace_id, winner_id,
                                              row.topic, row.statement,
                                              row.predicate, row.value)
                winner_claim = await self._claim_by_identity(s, new_identity)
                if winner_claim is None or winner_claim.id == row.id:
                    row.subject_entity_id = winner_id
                    row.identity_hash = new_identity
                    moved += 1
                else:   # identity collision → claim-merge with lineage
                    row.subject_entity_id = winner_id
                    await self.merge_claims(s, row, winner_claim.id)
                    collided += 1
            edge_rows = (await s.execute(select(EdgeRow).where(
                (EdgeRow.source_entity_id == loser_id) |
                (EdgeRow.target_entity_id == loser_id)))).scalars().all()
            for e in edge_rows:
                src = winner_id if e.source_entity_id == loser_id else e.source_entity_id
                tgt = winner_id if e.target_entity_id == loser_id else e.target_entity_id
                dup = (await s.execute(select(EdgeRow).where(
                    EdgeRow.workspace_id == e.workspace_id,
                    EdgeRow.source_entity_id == src, EdgeRow.relation == e.relation,
                    EdgeRow.target_entity_id == tgt, EdgeRow.id != e.id))).scalar_one_or_none()
                if dup is None:
                    e.source_entity_id, e.target_entity_id = src, tgt
                else:
                    dup_have = {r for (r,) in (await s.execute(
                        select(EdgeEvidenceRow.evidence_id)
                        .where(EdgeEvidenceRow.edge_id == dup.id))).all()}
                    for (ev,) in (await s.execute(select(EdgeEvidenceRow.evidence_id)
                                                  .where(EdgeEvidenceRow.edge_id == e.id))).all():
                        if ev not in dup_have:
                            s.add(EdgeEvidenceRow(edge_id=dup.id, evidence_id=ev))
                            dup_have.add(ev)
                    await s.execute(EdgeEvidenceRow.__table__.delete()
                                    .where(EdgeEvidenceRow.edge_id == e.id))
                    await s.delete(e)
            loser_row = await s.get(EntityRow, loser_id)
            loser_row.merged_into = winner_id
            s.add(EntityMergeLogRow(id=_eid(), loser_id=loser_id, winner_id=winner_id,
                                    score=score, method=method,
                                    at=datetime.now(timezone.utc).isoformat()))
            await s.commit()
        if loser:
            await self.add_alias(workspace_id, winner_id, loser.name)
            for a in loser.aliases:
                await self.add_alias(workspace_id, winner_id, a)
        return {"merged": True, "claims_moved": moved, "claims_collided": collided}

    # ================= row → ontology mappers ------------------------------
    @staticmethod
    def _ev(r: EvidenceRow) -> Evidence:
        return Evidence(id=r.id, url=r.url, canonical_url=r.canonical_url,
                        domain=r.domain, title=r.title, content=r.content,
                        source_type=r.source_type, published_date=r.published_date,
                        retrieved_at=r.retrieved_at, quality_score=r.quality_score,
                        visibility=r.visibility)

    @staticmethod
    def _ent(r: EntityRow) -> Entity:
        return Entity(id=r.id, workspace_id=r.workspace_id, type=r.type,
                      name=r.name, aliases=r.aliases or [], attributes=r.attributes or {})

    @staticmethod
    def _edge(r: EdgeRow) -> Edge:
        return Edge(id=r.id, workspace_id=r.workspace_id,
                    source_entity_id=r.source_entity_id, relation=r.relation,
                    target_entity_id=r.target_entity_id,
                    evidence_ids=r.evidence_ids or [],
                    trust=TrustVector(**(r.trust or {})), as_of=r.as_of,
                    claim_id=r.claim_id)

    @staticmethod
    def _claim(r: ClaimRow) -> Claim:
        return Claim(id=r.id, workspace_id=r.workspace_id,
                     subject_entity_id=r.subject_entity_id, kind=r.kind,
                     statement=r.statement, value=r.value,
                     value_entity_id=r.value_entity_id,
                     predicate=r.predicate, topic=r.topic,
                     as_of=r.as_of, evidence_ids=r.evidence_ids or [],
                     trust=trust_at_read(r.trust or {}, r.as_of, r.created_at),
                     status=r.status,
                     superseded_by=r.superseded_by, source_type=r.source_type,
                     run_id=r.run_id, created_at=r.created_at)

    @staticmethod
    def _insight(r: InsightRow) -> Insight:
        return Insight(id=r.id, workspace_id=r.workspace_id,
                       organization_id=r.organization_id, kind=r.kind,
                       title=r.title, body=r.body, claim_ids=r.claim_ids or [],
                       trust=TrustVector(**(r.trust or {})),
                       authored_by=r.authored_by, debate_status=r.debate_status,
                       run_id=r.run_id, created_at=r.created_at)
