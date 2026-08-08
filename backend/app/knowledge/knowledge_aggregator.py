"""Evidence collection over the SearchPlan — fully parallel across all
categories AND queries (the old version serialized categories)."""
import asyncio

from app.core.events import Event, bus
from app.core.logging import get_logger
from app.schemas.plan import SearchPlan

log = get_logger("knowledge")


class KnowledgeAggregator:
    async def build(self, ctx, plan: SearchPlan) -> dict:
        settings_max = 5
        jobs: list[tuple[str, str]] = [
            (category, query)
            for category, queries in plan.categories().items()
            for query in queries
        ]

        async def one(category: str, query: str):
            try:
                results = await ctx.search.search(query, max_results=settings_max)
                return category, query, [r.as_dict() for r in results], None
            except Exception as exc:
                log.warning("run_id=%s search failed category=%s: %s", ctx.run_id, category, exc)
                return category, query, [], str(exc)

        outcomes = await asyncio.gather(*(one(c, q) for c, q in jobs))

        knowledge: dict[str, list] = {c: [] for c in plan.categories()}
        for category, query, results, error in outcomes:
            entry = {"query": query, "results": results}
            if error:
                entry["error"] = error
            knowledge[category].append(entry)

        total = sum(len(e["results"]) for lst in knowledge.values() for e in lst)
        await bus.publish(Event("research.collected", ctx.run_id,
                                {"queries": len(jobs), "results": total}))
        return knowledge
