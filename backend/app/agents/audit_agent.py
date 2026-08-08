from app.agents.base_agent import BaseAgent
from app.analyzers.website_analyzer import analyze_website
from app.providers.llm.base import Tier
from app.utils.prompts import audit_prompt


class AuditAgent(BaseAgent):
    key = "audit"
    name = "Audit Agent"

    async def run(self, ctx, **kwargs) -> dict:
        analysis = await analyze_website(str(ctx.request.website))
        prompt = audit_prompt(ctx.request.company_name, str(ctx.request.website), analysis)
        result = await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="audit")
        result["_measured_signals"] = analysis  # provenance for the LLM assessment
        return result
