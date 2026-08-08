from tavily import AsyncTavilyClient

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.throttle import search_cache, stable_key
from app.providers.search.base import SearchResult

log = get_logger("search.tavily")


def _normalize_query(query: str) -> str:
    """Normalize for cache keying so trivially-different intents share a result:
    lowercase, collapse whitespace, strip surrounding punctuation. This is what
    turns 'OpenAI pricing', 'openai   pricing', and 'OpenAI pricing?' into one
    cached search instead of three Tavily hits."""
    import re
    q = query.strip().lower()
    q = re.sub(r"\s+", " ", q)
    q = q.strip(" .?!,")
    return q


class TavilyProvider:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)
        self._settings = get_settings()

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        s = self._settings
        # ---- Search cache (Priority Zero): dedupe identical Tavily searches ---
        key = stable_key("tavily.v1", _normalize_query(query), max_results,
                         s.search_depth, s.search_content_max_chars)

        async def _fetch() -> list[dict]:
            response = await self._client.search(
                query=query, search_depth=s.search_depth, max_results=max_results,
            )
            out = []
            for item in response.get("results", []):
                content = item.get("content", "") or ""
                if s.search_content_max_chars:
                    content = content[: s.search_content_max_chars]
                out.append({
                    "title": item.get("title", "") or "",
                    "url": item.get("url", "") or "",
                    "content": content,
                    "score": item.get("score"),
                    "published_date": item.get("published_date"),
                })
            return out

        # single-flight + TTL: concurrent specialists asking the same thing wait
        # on one upstream call rather than each hitting Tavily.
        raw = await search_cache.get_or_compute(key, _fetch)
        return [SearchResult(title=r["title"], url=r["url"], content=r["content"],
                             score=r["score"], published_date=r["published_date"])
                for r in raw]


def build_search_provider():
    s = get_settings()
    if s.search_provider == "tavily":
        return TavilyProvider(api_key=s.tavily_api_key)
    raise ValueError(f"Unknown search_provider: {s.search_provider}")
