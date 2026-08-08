"""Merges per-query results into per-category evidence lists.

Honest naming note: this does NOT summarize; it consolidates. It is replaced
by the Intelligence Graph ingestion in Phase 1 (Blueprint Part V).
"""
from app.agents.base_agent import BaseAgent


class ResearchConsolidatorAgent(BaseAgent):
    key = "research_summarizer"
    name = "Research Consolidator"

    async def run(self, ctx, *, knowledge: dict, **kwargs) -> dict:
        shared: dict[str, list] = {}
        for category, items in knowledge.items():
            merged: list = []
            seen_urls: set[str] = set()
            for item in items:
                for result in item.get("results", []):
                    url = (result.get("url") or "").rstrip("/")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    merged.append(result)
            shared[category] = merged
        return shared
