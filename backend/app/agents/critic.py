"""The Critic (Phase 3) — judge-tier adjudication and review.

Two duties:
1. Dispute adjudication: examine both claims of an open dispute with their
   evidence and read-time trust; uphold one side or DEFER. Fail-safe:
   malformed/uncited/overreaching verdicts defer, never destroy.
2. Insight review: challenge each unreviewed insight against its cited
   claims; debate_status → validated | rejected, with rationale.

Deterministic guardrails around the LLM (the LLM proposes, the code disposes):
- A verdict may only cite evidence actually linked to the involved claims.
- The Critic cannot overrule a trust gap larger than TRUST_GATE_BAND in the
  weaker claim's favor unless it cites at least one evidence item the stronger
  claim lacks.
- All writes go through tools (graph.resolve_dispute / graph.review_insight).
"""
from app.core.events import Event, bus
from app.core.logging import get_logger
from app.graph.diff import TRUST_GATE_BAND
from app.providers.llm.base import Tier
from app.tools.registry import BudgetExceeded, ToolContext, registry

log = get_logger("critic")

MAX_DISPUTES_PER_RUN = 5
MAX_REVIEWS_PER_RUN = 10

_ADJUDICATE_PROMPT = """You are the dispute adjudicator for an intelligence graph.

Two claims about the same fact disagree. Decide which is better supported, or
defer if the evidence is not decisive.

FACT IN DISPUTE: {predicate} of {subject}

CLAIM A (id={a_id}, value="{a_value}", as_of={a_asof}, confidence={a_conf}):
"{a_statement}"
Evidence for A:
{a_evidence}

CLAIM B (id={b_id}, value="{b_value}", as_of={b_asof}, confidence={b_conf}):
"{b_statement}"
Evidence for B:
{b_evidence}

Judge ONLY on the evidence shown: source authority (official/gov > news >
blogs), recency of the underlying pages, specificity, and internal consistency.
If neither side is clearly better supported, defer.

Return JSON:
{{"winner": "{a_id}" | "{b_id}" | null,
  "rationale": "2-3 sentences grounded in the evidence",
  "citations": ["evidence ids that support the verdict"]}}
"""

_REVIEW_PROMPT = """You are the insight critic for an intelligence graph.

Challenge the following insight against the claims it cites. An insight is
VALID only if every material assertion in it is supported by the cited claims;
reject insights that overreach, speculate beyond the claims, or misstate them.

INSIGHT ({kind}): {title}
{body}

CITED CLAIMS:
{claims}

Return JSON:
{{"verdict": "validated" | "rejected",
  "rationale": "1-2 sentences; if rejected, name the unsupported assertion"}}
"""


def _fmt_evidence(evidence) -> str:
    return "\n".join(f"- [{e.id}] {e.domain} ({e.published_date or 'undated'}, "
                     f"quality {e.quality_score:.2f}): {e.title} — "
                     f"{' '.join(e.content.split())[:280]}"
                     for e in evidence) or "- none"


class Critic:
    key = "critic"

    # ---------------- dispute adjudication ---------------------------------
    async def adjudicate_disputes(self, ctx: ToolContext) -> dict:
        stats = {"adjudicated": 0, "deferred": 0, "resolved": 0}
        disputes = [i for i in await registry.invoke(ctx, "graph.insights", kind="dispute")
                    if i.debate_status not in ("resolved", "deferred")]
        for dispute in disputes[:MAX_DISPUTES_PER_RUN]:
            try:
                outcome = await self._adjudicate(ctx, dispute)
            except BudgetExceeded:
                break
            except Exception as exc:
                log.warning("adjudication failed open (defer) %s: %s", dispute.id, exc)
                outcome = {"winner": None, "rationale": f"adjudication error: {exc}",
                           "citations": []}
            stats["adjudicated"] += 1
            result = await registry.invoke(ctx, "graph.resolve_dispute",
                                           insight_id=dispute.id,
                                           winner_claim_id=outcome["winner"],
                                           rationale=outcome["rationale"])
            stats["resolved" if result["resolved"] else "deferred"] += 1
            await bus.publish(Event("dispute.adjudicated", ctx.run_id,
                                    {"insight_id": dispute.id,
                                     "resolved": result["resolved"]}))
        return stats

    async def _adjudicate(self, ctx: ToolContext, dispute) -> dict:
        claims = await ctx.graph.get_claims(dispute.claim_ids)
        live = [c for c in claims if c.status == "active"]
        if len(live) != 2:
            return {"winner": None, "rationale": "conflict no longer live", "citations": []}
        a, b = live
        ev_a = await ctx.graph.get_evidence(a.evidence_ids)
        ev_b = await ctx.graph.get_evidence(b.evidence_ids)
        subject = await ctx.graph.get_entity(a.subject_entity_id)
        raw = await ctx.llm.complete_json(
            _ADJUDICATE_PROMPT.format(
                predicate=a.predicate or "value", subject=subject.name if subject else "?",
                a_id=a.id, a_value=a.value, a_asof=a.as_of, a_conf=a.trust.confidence,
                a_statement=a.statement, a_evidence=_fmt_evidence(ev_a),
                b_id=b.id, b_value=b.value, b_asof=b.as_of, b_conf=b.trust.confidence,
                b_statement=b.statement, b_evidence=_fmt_evidence(ev_b)),
            tier=Tier.JUDGE, label="adjudicate_dispute")

        winner_id = raw.get("winner")
        citations = [c for c in (raw.get("citations") or []) if isinstance(c, str)]
        rationale = str(raw.get("rationale", ""))[:800]
        if winner_id not in (a.id, b.id):
            return {"winner": None, "rationale": rationale or "no decisive winner",
                    "citations": []}
        winner, loser = (a, b) if winner_id == a.id else (b, a)
        legal = set(winner.evidence_ids) | set(loser.evidence_ids)
        cited = [c for c in citations if c in legal]
        if not cited:
            return {"winner": None,
                    "rationale": "verdict rejected: cited no linked evidence",
                    "citations": []}
        # trust-gap guardrail: upholding the clearly weaker side needs evidence
        # the stronger side lacks
        if winner.trust.confidence < loser.trust.confidence - TRUST_GATE_BAND:
            exclusive = set(winner.evidence_ids) - set(loser.evidence_ids)
            if not (set(cited) & exclusive):
                return {"winner": None,
                        "rationale": "verdict rejected: overruled trust gap "
                                     "without exclusive evidence",
                        "citations": []}
        return {"winner": winner.id, "rationale": rationale, "citations": cited}

    # ---------------- insight review ----------------------------------------
    async def review_insights(self, ctx: ToolContext,
                              insight_ids: list[str]) -> dict:
        stats = {"reviewed": 0, "validated": 0, "rejected": 0}
        for insight_id in insight_ids[:MAX_REVIEWS_PER_RUN]:
            rows = [i for i in await registry.invoke(ctx, "graph.insights")
                    if i.id == insight_id]
            if not rows or rows[0].kind.value in ("dispute",):
                continue
            insight = rows[0]
            claims = await ctx.graph.get_claims(insight.claim_ids)
            try:
                raw = await ctx.llm.complete_json(
                    _REVIEW_PROMPT.format(
                        kind=insight.kind.value, title=insight.title,
                        body=insight.body[:1500],
                        claims="\n".join(f"- [{c.id}] ({c.status}, conf "
                                         f"{c.trust.confidence}) {c.statement}"
                                         for c in claims)),
                    tier=Tier.JUDGE, label="review_insight")
                verdict = raw.get("verdict")
                if verdict not in ("validated", "rejected"):
                    verdict = "validated" if all(
                        c.status == "active" for c in claims) else "rejected"
                rationale = str(raw.get("rationale", ""))[:400]
            except BudgetExceeded:
                break
            except Exception as exc:            # fail-open: leave unreviewed
                log.warning("review failed open %s: %s", insight_id, exc)
                continue
            await registry.invoke(ctx, "graph.review_insight",
                                  insight_id=insight_id, verdict=verdict,
                                  rationale=rationale)
            stats["reviewed"] += 1
            stats[verdict] += 1
        return stats
