"""Fake providers — tests never touch the network (rule 6 makes this trivial)."""
import json

from app.providers.llm.base import LLMResult
from app.providers.search.base import SearchResult

PLAN = {"market": ["m q"], "competitors": ["c q1", "c q2"], "pricing": ["p q"],
        "technology": ["t q"], "seo": ["s q"], "social": ["so q"], "leads": ["l q"]}


class FakeLLM:
    """Returns canned JSON per label; can be told to fail specific labels."""
    def __init__(self, fail_labels: set[str] | None = None,
                 bad_json_labels: set[str] | None = None):
        self.fail = fail_labels or set()
        self.bad_json = bad_json_labels or set()
        self.calls: list[str] = []
        self._bad_served: set[str] = set()

    async def complete_json(self, *, model, system, prompt, temperature, timeout):
        label = "search_planner" if "Search Planner" in prompt else None
        # label inference by prompt markers
        markers = {"Market Research Consultant": "market",
                   "Competitive Intelligence": "competitor",
                   "Sales Intelligence": "lead",
                   "Pricing Intelligence": "pricing",
                   "Website Audit": "audit",
                   "Growth Strategist": "opportunity",
                   "B2B Sales Consultant": "outreach"}
        for marker, name in markers.items():
            if marker in prompt:
                label = name
        self.calls.append(label or "unknown")
        if label in self.fail:
            raise RuntimeError(f"simulated failure in {label}")
        if label in self.bad_json and label not in self._bad_served:
            self._bad_served.add(label)  # fail once, then repair succeeds
            return LLMResult("not json {", model, 10, 5)
        payload = PLAN if label == "search_planner" else {"agent": label, "ok": True}
        return LLMResult(json.dumps(payload), model, 100, 50)


class FakeSearch:
    async def search(self, query, *, max_results):
        return [SearchResult(title=f"t:{query}", url=f"https://ex.com/{abs(hash(query))%99}",
                             content="Full evidence content " * 20)]
