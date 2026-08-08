from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.utils.prompts import outreach_prompt


class OutreachAgent(BaseAgent):
    key = "outreach"
    name = "Outreach Agent"

    async def run(self, ctx, *, opportunity: dict, **kwargs) -> dict:
        prompt = outreach_prompt(ctx.request.company_name, opportunity)
        return await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="outreach")
