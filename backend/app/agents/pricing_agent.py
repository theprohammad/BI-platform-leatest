from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.utils.prompts import pricing_prompt


class PricingAgent(BaseAgent):
    key = "pricing"
    name = "Pricing Agent"

    async def run(self, ctx, *, intelligence: dict, **kwargs) -> dict:
        research = intelligence.get("pricing", [])
        prompt = pricing_prompt(ctx.request.company_name, ctx.request.industry, research)
        result = await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="pricing")
        ctx.memory.set("pricing", result)
        return result
