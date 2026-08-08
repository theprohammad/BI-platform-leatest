"""Deep website intelligence — real analysis of fetched HTML + headers.

Everything here is *measured* from the actual page (Rule 2: never fabricated).
The fetch is separated from the analysis so the analysis is fully unit-testable
against fixture HTML, and so the same analyzer feeds three products:

  * SEO / Website Audit (technical SEO, headings, meta, schema, images, links)
  * Competitive Intelligence (homepage/pricing snapshot + tech + messaging)
  * Company enrichment (title, description, social profiles, tech stack)

Data that genuinely requires an external provider (keyword volumes, backlinks,
traffic, verified emails) is NOT invented here — those live behind explicit
connectors and surface "Not available from connected providers" when absent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# ---- Technology fingerprints (HTML/script signatures, not a paid DB) --------
# Conservative, signature-based detection from page source. Each hit is real
# evidence (the marker is literally present in the HTML).
_TECH_SIGNATURES: dict[str, list[str]] = {
    "React": [r"__REACT_DEVTOOLS", r"data-reactroot", r"react(?:\.min)?\.js"],
    "Next.js": [r"/_next/", r"__NEXT_DATA__"],
    "Vue.js": [r"data-v-[0-9a-f]{8}", r"vue(?:\.min)?\.js"],
    "Angular": [r"ng-version", r"ng-app"],
    "Svelte": [r"svelte-[0-9a-z]+"],
    "WordPress": [r"/wp-content/", r"/wp-includes/"],
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
    "Wix": [r"static\.wixstatic\.com", r"wix\.com"],
    "Squarespace": [r"squarespace\.com", r"static1\.squarespace"],
    "Webflow": [r"assets\.website-files\.com", r"webflow\.js"],
    "HubSpot": [r"js\.hs-scripts\.com", r"hs-analytics"],
    "Google Analytics": [r"google-analytics\.com/analytics\.js", r"gtag\('config'", r"googletagmanager\.com/gtag"],
    "Google Tag Manager": [r"googletagmanager\.com/gtm\.js"],
    "Segment": [r"cdn\.segment\.com"],
    "Intercom": [r"widget\.intercom\.io"],
    "Drift": [r"js\.driftt\.com"],
    "Stripe": [r"js\.stripe\.com"],
    "Cloudflare": [r"cdnjs\.cloudflare\.com", r"__cf"],
    "Tailwind CSS": [r"tailwind"],
    "Bootstrap": [r"bootstrap(?:\.min)?\.css", r"bootstrap(?:\.min)?\.js"],
    "jQuery": [r"jquery(?:\.min)?\.js"],
    "Marketo": [r"munchkin\.marketo"],
    "Salesforce": [r"salesforce\.com", r"pardot"],
}

_SOCIAL_HOSTS = {
    "linkedin.com": "LinkedIn", "twitter.com": "Twitter/X", "x.com": "Twitter/X",
    "facebook.com": "Facebook", "instagram.com": "Instagram", "youtube.com": "YouTube",
    "github.com": "GitHub", "tiktok.com": "TikTok", "crunchbase.com": "Crunchbase",
}

_SECURITY_HEADERS = [
    "strict-transport-security", "content-security-policy", "x-frame-options",
    "x-content-type-options", "referrer-policy", "permissions-policy",
]


@dataclass
class PageAnalysis:
    """A structured, fully-measured analysis of one page."""
    url: str
    final_url: str = ""
    status_code: int | None = None
    # SEO core
    title: str = ""
    title_length: int = 0
    meta_description: str = ""
    meta_description_length: int = 0
    canonical: str | None = None
    robots_meta: str | None = None
    lang: str | None = None
    viewport: str | None = None
    charset: str | None = None
    # headings
    h1: list[str] = field(default_factory=list)
    heading_counts: dict[str, int] = field(default_factory=dict)
    # open graph / twitter
    open_graph: dict[str, str] = field(default_factory=dict)
    twitter_card: dict[str, str] = field(default_factory=dict)
    # structured data
    schema_types: list[str] = field(default_factory=list)
    has_json_ld: bool = False
    # images
    image_count: int = 0
    images_missing_alt: int = 0
    # links
    internal_links: int = 0
    external_links: int = 0
    nofollow_links: int = 0
    social_profiles: dict[str, str] = field(default_factory=dict)
    # content
    word_count: int = 0
    text_html_ratio: float = 0.0
    # tech + security
    technologies: list[str] = field(default_factory=list)
    security_headers: dict[str, bool] = field(default_factory=dict)
    is_https: bool = False
    # derived issues (each is a real, explainable finding)
    issues: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _detect_tech(html: str) -> list[str]:
    found = []
    for tech, patterns in _TECH_SIGNATURES.items():
        if any(re.search(p, html, re.IGNORECASE) for p in patterns):
            found.append(tech)
    return sorted(found)


def _social_profiles(links: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for href in links:
        host = urlparse(href).netloc.lower().removeprefix("www.")
        for domain, name in _SOCIAL_HOSTS.items():
            if host.endswith(domain) and name not in out:
                out[name] = href
    return out


def analyze_html(url: str, html: str, *, status_code: int | None = None,
                 final_url: str | None = None,
                 response_headers: dict[str, str] | None = None) -> PageAnalysis:
    """Pure analysis of already-fetched content. No network — fully testable."""
    soup = BeautifulSoup(html, "html.parser")
    headers = {k.lower(): v for k, v in (response_headers or {}).items()}
    a = PageAnalysis(url=url, final_url=final_url or url, status_code=status_code)

    # --- core SEO ---
    if soup.title and soup.title.string:
        a.title = soup.title.string.strip()
    a.title_length = len(a.title)
    md = soup.find("meta", attrs={"name": "description"})
    a.meta_description = (md.get("content", "") if md else "").strip()
    a.meta_description_length = len(a.meta_description)
    can = soup.find("link", attrs={"rel": "canonical"})
    a.canonical = can.get("href") if can else None
    rob = soup.find("meta", attrs={"name": "robots"})
    a.robots_meta = rob.get("content") if rob else None
    html_tag = soup.find("html")
    a.lang = html_tag.get("lang") if html_tag else None
    vp = soup.find("meta", attrs={"name": "viewport"})
    a.viewport = vp.get("content") if vp else None
    cs = soup.find("meta", attrs={"charset": True})
    a.charset = cs.get("charset") if cs else None

    # --- headings ---
    for level in range(1, 7):
        tags = soup.find_all(f"h{level}")
        a.heading_counts[f"h{level}"] = len(tags)
        if level == 1:
            a.h1 = [t.get_text(strip=True) for t in tags]

    # --- open graph / twitter ---
    for m in soup.find_all("meta"):
        prop = m.get("property", "")
        if prop.startswith("og:"):
            a.open_graph[prop[3:]] = m.get("content", "")
        name = m.get("name", "")
        if name.startswith("twitter:"):
            a.twitter_card[name[8:]] = m.get("content", "")

    # --- structured data ---
    ld = soup.find_all("script", attrs={"type": "application/ld+json"})
    a.has_json_ld = len(ld) > 0
    types: set[str] = set()
    for block in ld:
        for m in re.finditer(r'"@type"\s*:\s*"([^"]+)"', block.get_text() or ""):
            types.add(m.group(1))
    a.schema_types = sorted(types)

    # --- images ---
    imgs = soup.find_all("img")
    a.image_count = len(imgs)
    a.images_missing_alt = sum(1 for i in imgs if not i.get("alt"))

    # --- links ---
    base_host = urlparse(final_url or url).netloc
    all_hrefs = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        all_hrefs.append(urljoin(final_url or url, href))
        if link.get("rel") and "nofollow" in link.get("rel"):
            a.nofollow_links += 1
        host = urlparse(urljoin(final_url or url, href)).netloc
        if not host or host == base_host:
            a.internal_links += 1
        else:
            a.external_links += 1
    a.social_profiles = _social_profiles(all_hrefs)

    # --- content ---
    text = soup.get_text(" ", strip=True)
    a.word_count = len(text.split())
    a.text_html_ratio = round(len(text) / max(len(html), 1), 3)

    # --- tech + security ---
    a.technologies = _detect_tech(html)
    a.is_https = (final_url or url).startswith("https://")
    a.security_headers = {h: (h in headers) for h in _SECURITY_HEADERS}

    a.issues = _derive_issues(a)
    return a


def _derive_issues(a: PageAnalysis) -> list[dict]:
    """Turn measurements into real, explainable SEO/technical issues. Each has a
    severity, the evidence behind it, and a recommended fix (Semrush-style)."""
    issues: list[dict] = []

    def add(sev, code, message, fix):
        issues.append({"severity": sev, "code": code, "message": message, "fix": fix})

    if not a.title:
        add("high", "missing_title", "Page has no <title> tag.",
            "Add a unique, descriptive title of 50–60 characters.")
    elif a.title_length > 65:
        add("medium", "title_too_long",
            f"Title is {a.title_length} characters (over ~60).",
            "Shorten the title so it isn't truncated in search results.")
    elif a.title_length < 20:
        add("low", "title_too_short",
            f"Title is only {a.title_length} characters.",
            "Expand the title to be more descriptive (50–60 chars).")

    if not a.meta_description:
        add("medium", "missing_meta_description", "No meta description.",
            "Add a compelling 140–160 character description.")
    elif a.meta_description_length > 165:
        add("low", "meta_description_long",
            f"Meta description is {a.meta_description_length} characters.",
            "Trim to ~155 characters to avoid truncation.")

    h1n = a.heading_counts.get("h1", 0)
    if h1n == 0:
        add("high", "missing_h1", "Page has no H1 heading.",
            "Add a single H1 that summarizes the page.")
    elif h1n > 1:
        add("medium", "multiple_h1", f"Page has {h1n} H1 headings.",
            "Use exactly one H1 per page; demote the rest to H2.")

    if not a.canonical:
        add("low", "missing_canonical", "No canonical link.",
            "Add a rel=canonical to prevent duplicate-content dilution.")
    if not a.viewport:
        add("medium", "missing_viewport", "No responsive viewport meta.",
            "Add <meta name=viewport content='width=device-width, initial-scale=1'>.")
    if not a.lang:
        add("low", "missing_lang", "No lang attribute on <html>.",
            "Set <html lang='…'> for accessibility and international SEO.")
    if a.image_count and a.images_missing_alt:
        sev = "medium" if a.images_missing_alt / a.image_count > 0.3 else "low"
        add(sev, "images_missing_alt",
            f"{a.images_missing_alt} of {a.image_count} images lack alt text.",
            "Add descriptive alt text to every meaningful image.")
    if not a.has_json_ld:
        add("low", "no_structured_data", "No JSON-LD structured data found.",
            "Add schema.org markup (Organization, Product, FAQ, etc.).")
    if not a.is_https:
        add("high", "no_https", "Page is not served over HTTPS.",
            "Enable TLS and redirect all HTTP traffic to HTTPS.")
    missing_sec = [h for h, present in a.security_headers.items() if not present]
    if missing_sec:
        sev = "medium" if len(missing_sec) >= 4 else "low"
        add(sev, "missing_security_headers",
            f"Missing {len(missing_sec)} security headers: {', '.join(missing_sec)}.",
            "Add the missing headers (HSTS, CSP, X-Frame-Options, etc.).")
    if a.word_count < 200:
        add("low", "thin_content",
            f"Page has only ~{a.word_count} words of text.",
            "Consider expanding content depth for better topical coverage.")
    return issues


def health_scores(a: PageAnalysis) -> dict[str, int]:
    """Evidence-derived multi-dimensional scores (0–100). Every deduction traces
    to a real issue — never an arbitrary number (Rule 2/5)."""
    def score(codes: set[str], weights: dict[str, int]) -> int:
        s = 100
        for iss in a.issues:
            if iss["code"] in codes:
                s -= weights.get(iss["severity"], 5)
        return max(0, min(100, s))

    sev_w = {"high": 25, "medium": 12, "low": 5}
    technical = score({"no_https", "missing_viewport", "missing_canonical",
                       "missing_security_headers"}, sev_w)
    onpage = score({"missing_title", "title_too_long", "title_too_short",
                    "missing_meta_description", "meta_description_long",
                    "missing_h1", "multiple_h1"}, sev_w)
    content = score({"thin_content", "images_missing_alt", "no_structured_data"}, sev_w)
    security = score({"no_https", "missing_security_headers"}, sev_w)
    overall = round((technical + onpage + content + security) / 4)
    return {"technical": technical, "on_page": onpage, "content": content,
            "security": security, "overall": overall}


async def audit_website(url: str, *, timeout: float = 15.0) -> dict:
    """Live fetch + full analysis. Runs the real crawl in any environment with
    outbound network (your deployment). Returns analysis + health scores, or an
    honest error payload if the site can't be reached — never fabricated data.
    """
    import httpx

    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SentientIntelBot/1.0)"},
        ) as client:
            resp = await client.get(url)
        analysis = analyze_html(
            url, resp.text, status_code=resp.status_code,
            final_url=str(resp.url),
            response_headers=dict(resp.headers),
        )
        return {
            "ok": True,
            "analysis": analysis.as_dict(),
            "scores": health_scores(analysis),
            "fetched_at": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001 - report honestly, never fake
        return {
            "ok": False,
            "error": f"Could not fetch {url}: {type(exc).__name__}",
            "detail": str(exc)[:200],
            "fetched_at": _now_iso(),
        }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
