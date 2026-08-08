"""Per-run token & cost ledger (Blueprint Part VIII).

Rule 4 (research must get cheaper) is only enforceable if we can see cost.
Prices are config-shaped data; adjust as providers change.
"""
from dataclasses import dataclass, field

# USD per 1M tokens (indicative Groq pricing; update via ops, not code review)
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}


@dataclass
class LedgerEntry:
    label: str
    model: str
    prompt_tokens: int
    completion_tokens: int


@dataclass
class CostLedger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def add(self, label: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.entries.append(LedgerEntry(label, model, prompt_tokens, completion_tokens))

    @property
    def total_tokens(self) -> int:
        return sum(e.prompt_tokens + e.completion_tokens for e in self.entries)

    def estimated_cost_usd(self) -> float:
        total = 0.0
        for e in self.entries:
            pin, pout = PRICE_TABLE.get(e.model, (0.0, 0.0))
            total += e.prompt_tokens / 1e6 * pin + e.completion_tokens / 1e6 * pout
        return round(total, 6)

    def summary(self) -> dict:
        return {
            "llm_calls": len(self.entries),
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd(),
            "by_call": [
                {
                    "label": e.label,
                    "model": e.model,
                    "prompt_tokens": e.prompt_tokens,
                    "completion_tokens": e.completion_tokens,
                }
                for e in self.entries
            ],
        }
