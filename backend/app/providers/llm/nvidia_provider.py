from __future__ import annotations

from openai import AsyncOpenAI

from app.providers.llm.base import LLMResult


class NvidiaProvider:
    def __init__(self, api_key: str, base_url: str = "https://integrate.api.nvidia.com/v1") -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete_json(self, *, model: str, system: str, prompt: str,
                            temperature: float, timeout: float) -> LLMResult:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        usage = resp.usage
        return LLMResult(
            text=resp.choices[0].message.content or "",
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
