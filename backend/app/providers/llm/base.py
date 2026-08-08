"""LLM provider interface (Blueprint rule 6: provider independence).

Any provider (Groq, OpenAI, Anthropic, Gemini, ...) implements this protocol.
Nothing outside app/providers may import a vendor SDK.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Tier(str, Enum):
    EXTRACT = "extract"   # cheap/fast: extraction, mechanical checks
    REASON = "reason"     # specialists, chat
    JUDGE = "judge"       # critic on material disputes, CEO advisor


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLMProvider(Protocol):
    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float,
        timeout: float,
    ) -> LLMResult: ...
