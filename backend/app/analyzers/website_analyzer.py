"""Website signal collection — async, non-blocking (event loop stays free).

Phase 0 keeps the inherited shallow signals; Phase A replaces this with
measured Lighthouse/CWV data. The dict returned is explicitly labeled as
'signals', not an audit.
"""
import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings


async def analyze_website(url: str) -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.website_fetch_timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": "description"})
    meta_description = meta.get("content", "") if meta else ""

    images = soup.find_all("img")
    missing_alt = sum(1 for img in images if not img.get("alt"))
    internal_links = [a["href"] for a in soup.find_all("a", href=True) if a["href"].startswith("/")]
    external_links = [a["href"] for a in soup.find_all("a", href=True) if a["href"].startswith("http")]

    return {
        "final_url": str(response.url),
        "status_code": response.status_code,
        "title": title,
        "meta_description": meta_description,
        "h1_count": len(soup.find_all("h1")),
        "h2_count": len(soup.find_all("h2")),
        "images": len(images),
        "missing_alt": missing_alt,
        "internal_links": len(internal_links),
        "external_links": len(external_links),
    }
