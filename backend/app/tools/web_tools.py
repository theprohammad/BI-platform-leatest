"""World-facing tools. web.search is the only door to search providers."""
from pydantic import BaseModel

from app.tools.registry import Tool, ToolContext, registry


class WebSearchIn(BaseModel):
    query: str
    max_results: int = 5
    topic: str | None = None   # P5: budget envelope accounting


async def _web_search(ctx: ToolContext, p: WebSearchIn):
    return await ctx.search.search(p.query, max_results=p.max_results)


class WebFetchIn(BaseModel):
    url: str
    topic: str | None = None


async def _web_fetch(ctx: ToolContext, p: WebFetchIn):
    """S8: re-fetch a known page (refresh runs). Returns extracted text."""
    import httpx
    from bs4 import BeautifulSoup
    from app.core.config import get_settings
    async with httpx.AsyncClient(timeout=get_settings().website_fetch_timeout,
                                 follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get(p.url)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    return {"url": str(resp.url), "title": title, "text": text[:40000]}


registry.register(Tool("web.search", "Search the public web; returns full-content results.",
                       WebSearchIn, _web_search, cost_category="search"))
registry.register(Tool("web.fetch", "Fetch and extract text from a specific URL.",
                       WebFetchIn, _web_fetch, cost_category="search"))
