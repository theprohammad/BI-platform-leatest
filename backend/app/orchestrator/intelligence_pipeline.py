"""Phase A of a run: plan → collect → consolidate. Writes into ctx.memory."""
from app.agents.research_summarizer_agent import ResearchConsolidatorAgent
from app.agents.search_planner_agent import SearchPlannerAgent
from app.knowledge.knowledge_aggregator import KnowledgeAggregator


class IntelligencePipeline:
    def __init__(self) -> None:
        self.search_planner = SearchPlannerAgent()
        self.knowledge = KnowledgeAggregator()
        self.consolidator = ResearchConsolidatorAgent()

    async def run(self, ctx) -> dict:
        plan_envelope = await self.search_planner.execute(ctx)
        if plan_envelope["status"] != "completed":
            return {"status": "failed", "stage": "search_planning",
                    "error": plan_envelope.get("error"), "search_plan": None,
                    "shared_intelligence": {}}

        plan = plan_envelope["data"]
        ctx.memory.set("search_plan", plan)

        knowledge = await self.knowledge.build(ctx, plan)
        ctx.memory.set("knowledge", knowledge)

        consolidated_envelope = await self.consolidator.execute(ctx, knowledge=knowledge)
        shared = consolidated_envelope["data"] if consolidated_envelope["status"] == "completed" else {}
        ctx.memory.set("shared_intelligence", shared)

        return {
            "status": "completed",
            "search_plan": plan.model_dump(),
            "shared_intelligence": shared,
        }
