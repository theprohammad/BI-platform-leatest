"""Phase 1 fakes: hermetic providers for graph/loop/chat tests."""
import json

from app.providers.llm.base import LLMResult
from app.providers.search.base import SearchResult

UNI = "Acme University"

EXTRACTION = {
    "entities": [{"name": "Beta University", "type": "organization"},
                 {"name": "Lahore", "type": "location"}],
    "claims": [
        {"statement": f"{UNI} was founded in 2004.", "kind": "event",
         "subject": UNI, "predicate": "founded", "value": "2004",
         "as_of": "2004-01-01", "evidence": [1]},
        {"statement": f"{UNI} enrolls approximately 25,000 students.",
         "kind": "metric", "subject": UNI, "predicate": "enrollment",
         "value": "25000", "as_of": None, "evidence": [1, 2]},
        {"statement": "Beta University is a private university in Lahore.",
         "kind": "fact", "subject": "Beta University", "predicate": None,
         "value": None, "as_of": None, "evidence": [2]},
        {"statement": "This claim cites nothing and must be dropped.",
         "kind": "fact", "subject": UNI, "predicate": None, "value": None,
         "as_of": None, "evidence": []},
    ],
    "relations": [{"source": UNI, "relation": "competitor_of",
                   "target": "Beta University", "evidence": [2]}],
}

HYPOTHESES = {"hypotheses": [
    {"question": "Who are the main competitors?", "topic": "competitors",
     "queries": ["acme university competitors", "private universities lahore"]},
    {"question": "What is the tuition positioning?", "topic": "pricing",
     "queries": ["acme university tuition fees"]},
]}

VERIFY_ALL_GOOD = {"results": [{"claim": i, "supported": True} for i in range(1, 11)]}

INSIGHTS_TEMPLATE = {"insights": [{
    "title": "Beta University is the closest private peer",
    "body": "Both institutions are private and operate in Lahore, competing for the same students.",
    "kind": "finding", "claim_ids": ["__FILL__"]}]}


class ScriptedLLM:
    """Routes canned JSON by call label embedded in prompts."""
    def __init__(self, chat_payload=None, insight_claim_ids=None):
        self.calls = []
        self.chat_payload = chat_payload
        self.insight_claim_ids = insight_claim_ids or []

    async def complete_json_route(self, prompt):
        if "dispute adjudicator" in prompt:
            return {"winner": None, "rationale": "insufficient evidence",
                    "citations": []}           # default: defer (fail-safe)
        if "insight critic" in prompt:
            return {"verdict": "validated", "rationale": "supported by claims"}
        if "recommendation synthesizer" in prompt:
            return {"recommendations": []}
        if "market and positioning analyst" in prompt:
            return {"insights": []}
        if "pricing and value analyst" in prompt:
            return {"insights": []}
        if "reviewing first-wave findings" in prompt:
            return {"hypotheses": []}          # replan: nothing to follow up
        if "research director" in prompt:
            return HYPOTHESES
        if "information extraction engine" in prompt:
            return EXTRACTION
        if "verify citations" in prompt:
            return VERIFY_ALL_GOOD
        if "same real-world organization" in prompt:
            return {"same": False, "confidence": 0.2}
        if "competitive intelligence specialist" in prompt:
            payload = json.loads(json.dumps(INSIGHTS_TEMPLATE))
            payload["insights"][0]["claim_ids"] = self.insight_claim_ids or ["nonexistent"]
            return payload
        if "AI analyst" in prompt:
            return self.chat_payload or {"answer": "no", "cited_claim_ids": [],
                                         "needs_research": True, "proposed_research": "x"}
        if "Extract an analysis brief" in prompt:
            return {"organization": UNI, "website": None, "industry": "Higher Education",
                    "location": "Lahore", "objectives": ["competitors"],
                    "confidence": 0.9, "clarifying_question": None}
        return {}

    async def complete_json(self, *, model, system, prompt, temperature, timeout):
        self.calls.append(prompt[:40])
        return LLMResult(json.dumps(await self.complete_json_route(prompt)), model, 100, 50)


class FakeSearchV2:
    def __init__(self):
        self.queries = []

    async def search(self, query, *, max_results):
        self.queries.append(query)
        return [
            SearchResult(title=f"About {UNI}", url="https://acme.edu/about",
                         content=f"{UNI} was founded in 2004 in Lahore. " * 10,
                         published_date="2025-06-01"),
            SearchResult(title="University rankings Lahore",
                         url="https://news.example.com/rankings",
                         content=f"{UNI} enrolls about 25,000 students. Beta University is a private university in Lahore. " * 6,
                         published_date="2026-01-10"),
        ]
