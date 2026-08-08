"""Universal citation check (Blueprint §1.4): does the cited evidence actually
support the claim? Extract-tier, batched, mechanical. Claims that fail are
superseded-out, not deleted (lineage preserved).

TODO(phase-3): materiality-triggered full debate builds on top of this pass.
"""
from app.core.logging import get_logger
from app.providers.llm.base import Tier
from app.tools.registry import registry

log = get_logger("verification")

_PROMPT = """You verify citations for a business intelligence graph.

For each numbered claim, decide whether the quoted evidence excerpt supports it.
"supported" means the evidence states or directly entails the claim. Being
plausible is NOT enough.

Return JSON: {{"results": [{{"claim": 1, "supported": true}}]}}

{items}
"""


async def verify_claims(ctx, claim_ids: list[str], *, batch: int = 10) -> dict:
    """Returns {"checked": n, "failed": [claim_ids]}. Failed claims are marked
    superseded (kept for lineage/audit)."""
    failed: list[str] = []
    claims = await ctx.graph.get_claims(claim_ids)
    for i in range(0, len(claims), batch):
        chunk = claims[i:i + batch]
        items = []
        for j, c in enumerate(chunk, start=1):
            evidence = await ctx.graph.get_evidence(c.evidence_ids[:2])
            excerpt = " ... ".join(e.content[:600] for e in evidence)
            items.append(f"CLAIM {j}: {c.statement}\nEVIDENCE: {excerpt}\n")
        try:
            raw = await ctx.llm.complete_json(_PROMPT.format(items="\n".join(items)),
                                              tier=Tier.EXTRACT, label="verify")
        except Exception as exc:
            log.warning("verification batch failed open (claims kept): %s", exc)
            continue  # fail open: unverified ≠ false; trust vector still low-info
        for r in raw.get("results", []) or []:
            idx = r.get("claim")
            if isinstance(idx, int) and 1 <= idx <= len(chunk) and r.get("supported") is False:
                failed.append(chunk[idx - 1].id)
    if failed:
        await registry.invoke(ctx, "graph.set_claim_status",
                              claim_ids=failed, status="unsupported")
    return {"checked": len(claims), "failed": failed}
