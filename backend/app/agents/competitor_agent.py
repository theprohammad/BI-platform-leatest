from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.utils.prompts import competitor_prompt


class CompetitorAgent(BaseAgent):
    key = "competitor"
    name = "Competitor Agent"

    async def run(self, ctx, *, intelligence: dict, **kwargs) -> dict:
        research = intelligence.get("competitors", [])
        prompt = competitor_prompt(
            ctx.request.company_name, ctx.request.industry,
            ctx.request.target_market, research,
        )
        result = await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="competitor")
        ctx.memory.set("competitors", result)
        return result
