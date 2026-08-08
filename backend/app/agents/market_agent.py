from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.utils.prompts import market_prompt


class MarketAgent(BaseAgent):
    key = "market"
    name = "Market Agent"

    async def run(self, ctx, *, intelligence: dict, **kwargs) -> dict:
        research = intelligence.get("market", [])
        prompt = market_prompt(
            ctx.request.company_name, ctx.request.industry,
            ctx.request.target_market, research,
        )
        result = await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="market")
        ctx.memory.set("market", result)
        return result
