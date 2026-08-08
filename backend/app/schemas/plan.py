"""Validated search plan (kills the blind research["market"] KeyError class).

The planner LLM's output is coerced into this schema: unknown keys dropped,
missing keys defaulted, non-list values wrapped. Downstream code accesses
attributes, never raw dict keys.
"""
from pydantic import BaseModel, Field, field_validator

CATEGORIES = ("market", "competitors", "pricing", "technology", "seo", "social", "leads")


class SearchPlan(BaseModel):
    market: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    pricing: list[str] = Field(default_factory=list)
    technology: list[str] = Field(default_factory=list)
    seo: list[str] = Field(default_factory=list)
    social: list[str] = Field(default_factory=list)
    leads: list[str] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def _coerce(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(x) for x in v if x]
        return []

    def categories(self) -> dict[str, list[str]]:
        return {c: getattr(self, c) for c in CATEGORIES}

    def is_empty(self) -> bool:
        return not any(getattr(self, c) for c in CATEGORIES)
