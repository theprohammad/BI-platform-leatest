"""Phase 3 — the specialist swarm on a shared contract.

BaseSpecialist: gather graph context THROUGH TOOLS ONLY → reason (reason tier)
→ write cited Insights (store rejects uncited ones — rule 5). Subclasses
declare only what differs: which slice of the graph they read and how they
frame the analysis. Every specialist is versioned in AGENT_VERSIONS; which
specialists run is a playbook decision, not code.
"""
from app.core.logging import get_logger
from app.graph.ontology import TrustVector
from app.providers.llm.base import Tier
from app.tools.registry import BudgetExceeded, ToolContext, registry

log = get_logger("specialists")

_FRAME = """You are a {role}.

Organization: {org}

Below are graph claims (each with an id){extra_note}. Write 1-3 {focus}
insights. Every insight must cite the ids of the claims it is based on. Only
cite ids that appear below. If the claims are too thin for a meaningful
insight, return an empty list — do NOT invent.

Return JSON:
{{"insights": [{{"title":"", "body":"2-4 sentences of analysis, specific, no filler",
                "kind":"finding|recommendation", "claim_ids":["..."]}}]}}

CLAIMS:
{claims}
{extra}
"""


class BaseSpecialist:
    key = "base_specialist"
    role = "an analyst"
    focus = "analytical"

    async def gather(self, ctx: ToolContext, root_entity_id: str) -> tuple[dict, str, str]:
        """Returns (claims_by_id, extra_note, extra_block). Override per specialist."""
        raise NotImplementedError

    async def run(self, ctx: ToolContext, *, root_entity_id: str,
                  organization: str) -> list[str]:
        try:
            merged, extra_note, extra = await self.gather(ctx, root_entity_id)
        except BudgetExceeded:
            return []
        if not merged:
            return []
        claims_text = "\n".join(f"[{c.id}] ({c.topic}) {c.statement}"
                                for c in merged.values())
        try:
            raw = await ctx.llm.complete_json(
                _FRAME.format(role=self.role, org=organization, focus=self.focus,
                              extra_note=extra_note, claims=claims_text[:12000],
                              extra=extra),
                tier=Tier.REASON, label=self.key)
        except BudgetExceeded:
            return []
        except Exception as exc:                 # specialist isolation (B4 rule)
            log.warning("%s failed open: %s", self.key, exc)
            return []

        insight_ids: list[str] = []
        for ins in (raw.get("insights") or []):
            if not isinstance(ins, dict):
                continue
            cited = [c for c in (ins.get("claim_ids") or []) if c in merged]
            if not cited or not ins.get("title"):
                log.info("%s: dropped uncited insight %.60s", self.key,
                         ins.get("title", ""))
                continue
            trust_claims = [merged[c] for c in cited]
            avg_conf = sum(c.trust.confidence for c in trust_claims) / len(trust_claims)
            kind = ins.get("kind", "finding")
            insight_ids.append(await registry.invoke(
                ctx, "graph.write_insight",
                kind=kind if kind in ("finding", "recommendation") else "finding",
                title=str(ins["title"])[:300], body=str(ins.get("body", "")),
                claim_ids=cited, authored_by=self.key,
                trust=TrustVector(confidence=round(avg_conf, 3),
                                  evidence_count=sum(c.trust.evidence_count
                                                     for c in trust_claims))))
        return insight_ids


class CompetitorSpecialist(BaseSpecialist):
    key = "competitor_specialist"
    role = "competitive intelligence specialist"
    focus = "competitor"

    async def gather(self, ctx, root_entity_id):
        claims = await registry.invoke(ctx, "graph.claims",
                                       subject_entity_id=root_entity_id, limit=60)
        comp = await registry.invoke(ctx, "graph.claims", topic="competitors", limit=60)
        edges = await registry.invoke(ctx, "graph.edges", entity_id=root_entity_id,
                                      relation="competitor_of")
        merged = {c.id: c for c in [*claims, *comp]}
        edges_text = "\n".join(f"{e.source_entity_id} -> competitor_of -> {e.target_entity_id}"
                               for e in edges) or "none recorded"
        return merged, " and known competitor relationships", \
            f"\nCOMPETITOR EDGES:\n{edges_text}"


class MarketSpecialist(BaseSpecialist):
    key = "market_specialist"
    role = "market and positioning analyst"
    focus = "market-position"

    async def gather(self, ctx, root_entity_id):
        merged = {}
        for topic in ("market", "profile"):
            for c in await registry.invoke(ctx, "graph.claims",
                                           subject_entity_id=root_entity_id,
                                           topic=topic, limit=50):
                merged[c.id] = c
        return merged, "", ""


class PricingSpecialist(BaseSpecialist):
    key = "pricing_specialist"
    role = "pricing and value analyst"
    focus = "pricing"

    async def gather(self, ctx, root_entity_id):
        merged = {c.id: c for c in await registry.invoke(
            ctx, "graph.claims", topic="pricing", limit=60)}
        for c in await registry.invoke(ctx, "graph.claims",
                                       subject_entity_id=root_entity_id,
                                       topic="profile", limit=20):
            merged[c.id] = c
        return merged, " (pricing plus profile context)", ""


SPECIALISTS = {s.key: s for s in (CompetitorSpecialist(), MarketSpecialist(),
                                  PricingSpecialist())}
