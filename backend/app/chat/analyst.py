"""The AI Analyst — chat over the Intelligence Graph (Blueprint Part IV).

Hard rules enforced here:
- Retrieval ONLY through the Tool Layer (owner rule 8) — no store access.
- Answers cite claim ids that were actually retrieved; fabricated ids are
  stripped before the response leaves the server.
- Never regenerates research. If the graph can't answer, it says so and
  proposes a research task instead of hallucinating.
"""
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.providers.llm.base import Tier
from app.tools.registry import ToolContext, registry

log = get_logger("chat")

_PROMPT = """You are the AI analyst for an intelligence platform. Answer the user's
question using ONLY the graph claims and insights below.

Rules:
- Cite claims inline as [C:<id>] after each supported statement.
- Only cite ids that appear below. Uncited statements must be clearly framed
  as reasoning, not fact.
- If the graph does not contain the answer, say so plainly and set
  needs_research=true with a one-line proposed research task. Do not guess.
- Be direct and specific. No filler.

Return JSON:
{{"answer": "markdown answer with [C:id] citations",
  "cited_claim_ids": ["..."],
  "needs_research": false,
  "proposed_research": null}}

ORGANIZATION: {org}

CLAIMS:
{claims}

INSIGHTS:
{insights}

QUESTION: {question}
"""


class ChatAnswer(BaseModel):
    answer: str
    citations: list[dict] = Field(default_factory=list)  # {claim_id, statement, evidence:[{url,title}]}
    needs_research: bool = False
    proposed_research: str | None = None


class AnalystChat:
    async def ask(self, ctx: ToolContext, *, organization: str,
                  root_entity_id: str, question: str) -> ChatAnswer:
        # ---- retrieve (tools only) ----------------------------------------
        by_query = await registry.invoke(ctx, "graph.search", query=question, limit=10)
        about_subject = await registry.invoke(ctx, "graph.claims",
                                              subject_entity_id=root_entity_id, limit=30)
        insights = await registry.invoke(ctx, "graph.insights")

        claims = {c.id: c for c in [*by_query, *about_subject]}
        if not claims:
            return ChatAnswer(answer="I don't have any research on this yet.",
                              needs_research=True,
                              proposed_research=f"Run an analysis of {organization}.")

        claims_text = "\n".join(
            f"[{c.id}] ({c.topic}, confidence {c.trust.confidence}) {c.statement}"
            for c in claims.values())
        # Phase 3: debate-aware ranking — critic-validated conclusions and
        # recommendations lead; rejected/stale never reach the analyst.
        def _rank(i):
            order = {"validated": 0, "unreviewed": 2, "deferred": 3}
            return (0 if i.kind.value == "recommendation" else 1,
                    order.get(i.debate_status, 2))
        usable = [i for i in insights
                  if i.debate_status not in ("rejected", "stale")
                  and i.kind.value != "dispute"]
        insights_text = "\n".join(
            f"- [{i.kind.value}|{i.debate_status}] {i.title}: {i.body}"
            for i in sorted(usable, key=_rank)) or "none yet"

        raw = await ctx.llm.complete_json(
            _PROMPT.format(org=organization, claims=claims_text[:14000],
                           insights=insights_text[:4000], question=question.strip()[:2000]),
            tier=Tier.REASON, label="chat")

        # ---- enforce citation integrity ------------------------------------
        cited = [cid for cid in (raw.get("cited_claim_ids") or []) if cid in claims]
        citations = []
        for cid in cited:
            c = claims[cid]
            evidence = await registry.invoke(ctx, "graph.evidence",
                                             evidence_ids=c.evidence_ids[:3])
            citations.append({"claim_id": cid, "statement": c.statement,
                              "trust": c.trust.model_dump(),
                              "evidence": [{"url": e.url, "title": e.title} for e in evidence]})

        answer = str(raw.get("answer", "")).strip()
        # strip citation markers for ids the model invented
        for token in set(_markers(answer)) - set(cited):
            answer = answer.replace(f"[C:{token}]", "")

        return ChatAnswer(answer=answer, citations=citations,
                          needs_research=bool(raw.get("needs_research")),
                          proposed_research=raw.get("proposed_research"))


def _markers(text: str) -> list[str]:
    import re
    return re.findall(r"\[C:([0-9a-f]+)\]", text)
