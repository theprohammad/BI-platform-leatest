from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.utils.prompts import lead_prompt


class LeadAgent(BaseAgent):
    key = "lead"
    name = "Lead Agent"

    async def run(self, ctx, *, intelligence: dict, **kwargs) -> dict:
        research = {
            "market": intelligence.get("market", []),
            "competitors": intelligence.get("competitors", []),
            "social": intelligence.get("social", []),
            "technology": intelligence.get("technology", []),
            "leads": intelligence.get("leads", []),
        }
        prompt = lead_prompt(
            ctx.request.company_name, ctx.request.industry,
            ctx.request.target_market, research,
        )
        result = await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="lead")
        ctx.memory.set("leads", result)
        return result
