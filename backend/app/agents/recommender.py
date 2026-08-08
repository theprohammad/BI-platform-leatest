"""Phase 3 — Recommendation synthesis (rule 5 chain end).

Takes VALIDATED insights (critic-passed) and synthesizes actionable
recommendations. A recommendation is just an Insight of kind=recommendation
citing the union of the source insights' claims — the full chain
Recommendation → Insights → Claims → Evidence stays queryable. Uncited or
malformed outputs are dropped, never written.
"""
from app.core.logging import get_logger
from app.graph.ontology import TrustVector
from app.providers.llm.base import Tier
from app.tools.registry import BudgetExceeded, ToolContext, registry

log = get_logger("recommender")

MAX_RECOMMENDATIONS = 3

_PROMPT = """You are a recommendation synthesizer for a business-intelligence platform.

Organization: {org}

Below are VALIDATED insights (critic-reviewed) with the claim ids they cite.
Synthesize at most {n} concrete, actionable recommendations for this
organization. Each must be grounded in the insights shown and list the claim
ids (from the insights' citations) that justify it. If the insights don't
support a confident recommendation, return an empty list — do NOT pad.

Return JSON:
{{"recommendations": [{{"title":"", "body":"2-4 sentences: what to do and why",
                       "claim_ids":["..."]}}]}}

VALIDATED INSIGHTS:
{insights}
"""


class Recommender:
    key = "recommender"

    async def run(self, ctx: ToolContext, *, organization: str) -> list[str]:
        insights = [i for i in await registry.invoke(ctx, "graph.insights")
                    if i.debate_status == "validated"
                    and i.kind.value in ("finding", "signal")]
        if not insights:
            return []
        legal_claims = {cid for i in insights for cid in i.claim_ids}
        text = "\n\n".join(
            f"[{i.kind.value}] {i.title}\n{i.body[:600]}\ncites: {i.claim_ids}"
            for i in insights[:12])
        try:
            raw = await ctx.llm.complete_json(
                _PROMPT.format(org=organization, n=MAX_RECOMMENDATIONS, insights=text),
                tier=Tier.JUDGE, label="recommend")
        except BudgetExceeded:
            return []
        except Exception as exc:
            log.warning("recommender failed open: %s", exc)
            return []

        out: list[str] = []
        claims_cache = {c.id: c for c in await ctx.graph.get_claims(list(legal_claims))}
        for rec in (raw.get("recommendations") or [])[:MAX_RECOMMENDATIONS]:
            if not isinstance(rec, dict) or not rec.get("title"):
                continue
            cited = [c for c in (rec.get("claim_ids") or []) if c in legal_claims]
            if not cited:
                log.info("dropped uncited recommendation %.60s", rec.get("title", ""))
                continue
            trust_claims = [claims_cache[c] for c in cited if c in claims_cache]
            avg = (sum(c.trust.confidence for c in trust_claims) / len(trust_claims)
                   if trust_claims else 0.3)
            out.append(await registry.invoke(
                ctx, "graph.write_insight", kind="recommendation",
                title=str(rec["title"])[:300], body=str(rec.get("body", "")),
                claim_ids=cited, authored_by=self.key,
                trust=TrustVector(confidence=round(avg, 3),
                                  evidence_count=sum(c.trust.evidence_count
                                                     for c in trust_claims))))
        return out
