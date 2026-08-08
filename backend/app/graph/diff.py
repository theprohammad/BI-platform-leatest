"""S7 — Conflict detection, trust-gated supersession, change reports.

Invoked from the write_claim tool after every claim write. Uses only ontology
objects and existing lifecycle primitives (freeze holds): supersession via
`supersede_claim`, disagreement via `Insight(kind=dispute)`, materiality via
`Insight(kind=signal)`.

Trust gate (spec S7): the new claim supersedes an incumbent only if it is
more recent AND its read-time confidence is within 0.15 below (or above) the
incumbent's. Otherwise the conflict is SURFACED as a dispute, never silently
resolved.
"""
from app.core.events import Event, bus
from app.core.logging import get_logger
from app.graph.ontology import Insight, InsightKind, TrustVector
from app.graph.predicates import classify, normalize_value

log = get_logger("diff")

TRUST_GATE_BAND = 0.15
WATCHED_PREDICATES = {"tuition", "pricing", "enrollment", "employees", "ceo",
                      "rector", "competitor_of", "funding", "acquired"}


def _recency(claim) -> str:
    return claim.as_of or claim.created_at


def _watched(ctx) -> set:
    playbook = getattr(ctx, "playbook", None)
    extra = set(playbook.watched_predicates) if playbook else set()
    return WATCHED_PREDICATES | extra


async def reconcile(ctx, subject_entity_id: str) -> dict:
    """B6 sweep: parallel writes can each pass conflict detection against the
    pre-existing world and never against each other, leaving contradictory
    ACTIVE claims. Run-end sweep re-litigates any functional predicate with
    multiple active values through the same gates."""
    out = {"groups": 0, "superseded": 0, "disputes": 0}
    groups = await ctx.graph.conflicting_value_groups(ctx.workspace_id,
                                                      subject_entity_id)
    for claims in groups:
        out["groups"] += 1
        newest = max(claims, key=_recency)
        result = await detect_and_apply(ctx, newest.id)
        out["superseded"] += len(result["superseded"])
        out["disputes"] += len(result["disputes"])
    if out["groups"]:
        await bus.publish(Event("graph.reconciled", ctx.run_id, out))
    return out


async def detect_and_apply(ctx, new_claim_id: str) -> dict:
    """Returns {"superseded": [old_ids], "disputes": [insight_ids]}.
    Preconditions (CLAIM_LIFECYCLE.md): the evaluated claim must be ACTIVE;
    only FUNCTIONAL predicates may supersede — multi-valued/unknown predicates
    accumulate values and never conflict across different values (D1)."""
    out = {"superseded": [], "disputes": []}
    new = (await ctx.graph.get_claims([new_claim_id]))
    if not new:
        return out
    new = new[0]
    if not new.predicate:
        return out          # prose-only claims don't structurally diff (fail-safe)
    if new.status != "active":
        return out          # dead claims never re-litigate (kills phantom disputes)
    if classify(new.predicate) != "functional":
        return out          # multi-valued: different values coexist (D1)

    conflicts = await ctx.graph.find_conflicting_claims(
        ctx.workspace_id, new.subject_entity_id, new.predicate, new_claim_id)
    for old in conflicts:
        if (old.value_entity_id and new.value_entity_id
                and old.value_entity_id == new.value_entity_id):
            continue        # same canonical entity under different spellings (B9)
        if _values_equal(old.value, new.value):
            continue
        newer = _recency(new) >= _recency(old)
        trust_ok = new.trust.confidence >= old.trust.confidence - TRUST_GATE_BAND
        if newer and trust_ok:
            await ctx.graph.supersede_claim(old.id, new.id, run_id=ctx.run_id)
            out["superseded"].append(old.id)
            await bus.publish(Event("claim.superseded", ctx.run_id, {
                "predicate": new.predicate, "old": old.value, "new": new.value}))
            if new.predicate in _watched(ctx) and ctx.organization_id:
                await _signal(ctx, new, old)
        else:
            insight_id = await _dispute(ctx, new, old)
            if insight_id:
                out["disputes"].append(insight_id)
    return out


def _values_equal(a: str | None, b: str | None) -> bool:
    # single normalization authority: graph/predicates.normalize_value (v1) —
    # identity and conflict detection must agree on value equality
    return normalize_value(str(a or "")) == normalize_value(str(b or ""))


async def _dispute(ctx, new, old) -> str | None:
    if not ctx.organization_id:
        return None
    # D3/A4: one OPEN dispute per claim pair — idempotent across re-encounters
    for existing in await ctx.graph.insights_citing_claim(old.id):
        if (existing.kind.value == "dispute"
                and existing.debate_status != "resolved"
                and new.id in existing.claim_ids):
            return None
    insight = Insight(
        id="", workspace_id=ctx.workspace_id, organization_id=ctx.organization_id,
        kind=InsightKind.DISPUTE,
        title=f"Conflicting values for {new.predicate}",
        body=(f"Sources disagree on '{new.predicate}': existing evidence says "
              f"'{old.value}' while newer/other evidence says '{new.value}'. "
              f"Neither is trusted enough to supersede the other."),
        claim_ids=[old.id, new.id],
        trust=TrustVector(confidence=min(new.trust.confidence, old.trust.confidence)),
        authored_by="diff_engine", run_id=ctx.run_id)
    insight_id = await ctx.graph.add_insight(insight)
    await bus.publish(Event("dispute.opened", ctx.run_id,
                            {"predicate": new.predicate}))
    return insight_id


async def _signal(ctx, new, old) -> None:
    insight = Insight(
        id="", workspace_id=ctx.workspace_id, organization_id=ctx.organization_id,
        kind=InsightKind.SIGNAL,
        title=f"{new.predicate} changed: {old.value} → {new.value}",
        body=f"A watched fact changed. Previous: '{old.value}'. Current: '{new.value}'.",
        claim_ids=[new.id], trust=new.trust,
        authored_by="diff_engine", run_id=ctx.run_id)
    await ctx.graph.add_insight(insight)


async def build_change_report(ctx, subject_entity_id: str, since_iso: str) -> dict:
    """Change report for a twin since a timestamp (spec S7)."""
    created = await ctx.graph.claims_created_since(ctx.workspace_id,
                                                   subject_entity_id, since_iso)
    new_claims = [c for c in created if c.status == "active"]
    supersessions = []
    for c in created:
        # claims superseded BY the new ones
        from sqlalchemy import select
        from app.graph.models import ClaimRow
        async with ctx.graph._session_for_reads() as s:
            olds = (await s.execute(select(ClaimRow).where(
                ClaimRow.superseded_by == c.id))).scalars().all()
        for old in olds:
            supersessions.append({"predicate": c.predicate,
                                  "old_value": old.value, "new_value": c.value,
                                  "old_claim": old.id, "new_claim": c.id})
    insights = await ctx.graph.insights(ctx.workspace_id, ctx.organization_id or "")
    disputes = [i.model_dump() for i in insights
                if i.kind.value == "dispute" and i.created_at >= since_iso]
    signals = [i.model_dump() for i in insights
               if i.kind.value == "signal" and i.created_at >= since_iso]
    events = [c.model_dump() for c in new_claims if c.kind.value == "event"]
    return {"since": since_iso,
            "new_claims": len(new_claims),
            "new_events": events,
            "supersessions": supersessions,
            "disputes_opened": disputes,
            "signals": signals}
