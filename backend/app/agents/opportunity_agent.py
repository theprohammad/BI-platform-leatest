from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.utils.prompts import opportunity_prompt


class OpportunityAgent(BaseAgent):
    key = "opportunity"
    name = "Opportunity Agent"

    async def run(self, ctx, *, market=None, competitors=None, leads=None,
                  audit=None, pricing=None, **kwargs) -> dict:
        prompt = opportunity_prompt(
            ctx.request.company_name,
            market or "No market analysis available.",
            competitors or "No competitor analysis available.",
            leads or "No lead analysis available.",
            audit or "No website audit available.",
            pricing or "No pricing analysis available.",
        )
        return await ctx.llm.complete_json(prompt, tier=Tier.JUDGE, label="opportunity")
