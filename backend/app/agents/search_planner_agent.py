from app.agents.base_agent import BaseAgent
from app.providers.llm.base import Tier
from app.schemas.plan import SearchPlan
from app.utils.prompts import search_planner_prompt


class SearchPlannerAgent(BaseAgent):
    key = "search_planner"
    name = "Search Planner"

    async def run(self, ctx, **kwargs) -> SearchPlan:
        prompt = search_planner_prompt(
            ctx.request.company_name, ctx.request.industry, ctx.request.target_market,
        )
        raw = await ctx.llm.complete_json(prompt, tier=Tier.REASON, label="search_planner")
        plan = SearchPlan.model_validate(raw)
        if plan.is_empty():
            raise ValueError("Planner returned an empty search plan")
        return plan
