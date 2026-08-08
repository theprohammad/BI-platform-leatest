"""Conversational intake (Blueprint Part VI): free text → AnalysisBrief.
Zero forms. If the message is too ambiguous to identify an organization,
returns ONE clarifying question instead of guessing (ChatGPT behavior)."""
from pydantic import BaseModel, Field

from app.providers.llm.base import Tier

_PROMPT = """Extract an analysis brief from the user's message.

Return JSON:
{{
  "organization": "official organization name, or null if genuinely unidentifiable",
  "website": "url if stated or confidently known, else null",
  "industry": "e.g. Higher Education, SaaS — infer if clear, else null",
  "location": "city/country if stated or clearly implied, else null",
  "objectives": ["what the user wants, in their words, max 6"],
  "confidence": 0.0,
  "clarifying_question": "ONE short question if organization is null or ambiguous, else null"
}}

Rules:
- If the user names any identifiable organization, set it; do not ask.
- Never invent a website.
- objectives default to ["general strategic analysis"] if none stated.

USER MESSAGE:
{message}
"""


class AnalysisBrief(BaseModel):
    organization: str | None = None
    website: str | None = None
    industry: str | None = None
    location: str | None = None
    objectives: list[str] = Field(default_factory=lambda: ["general strategic analysis"])
    confidence: float = 0.0
    clarifying_question: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return not self.organization


class IntakeAgent:
    key = "intake"

    async def run(self, llm, message: str) -> AnalysisBrief:
        raw = await llm.complete_json(_PROMPT.format(message=message.strip()[:4000]),
                                      tier=Tier.REASON, label="intake")
        brief = AnalysisBrief.model_validate({k: v for k, v in raw.items()
                                              if k in AnalysisBrief.model_fields})
        if not brief.objectives:
            brief.objectives = ["general strategic analysis"]
        return brief
