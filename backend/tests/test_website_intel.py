"""Real website-intelligence analyzer — proven against fixture HTML so the
analysis logic is verified without needing live network. Every assertion checks
a genuinely measured value (Rule 2: nothing fabricated)."""
import httpx
import pytest

from app.analyzers.website_intel import analyze_html, health_scores


@pytest.fixture
async def client(tmp_path):
    from app.db import session as db
    from app.main import app
    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/seo.db", use_alembic=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c

GOOD_PAGE = """
<!doctype html><html lang="en">
<head>
<meta charset="utf-8">
<title>Acme CRM — AI Sales Platform for Healthcare</title>
<meta name="description" content="Acme CRM helps healthcare teams close more deals with AI-assisted outreach and pipeline intelligence.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://acme.com/">
<meta property="og:title" content="Acme CRM"><meta property="og:image" content="https://acme.com/og.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
<script src="https://js.stripe.com/v3/"></script>
<div class="__NEXT_DATA__"></div>
</head>
<body>
<h1>AI CRM for Healthcare</h1><h2>Features</h2><h2>Pricing</h2>
<img src="a.png" alt="dashboard"><img src="b.png">
<a href="/features">Features</a><a href="/pricing">Pricing</a>
<a href="https://linkedin.com/company/acme">LinkedIn</a>
<a href="https://github.com/acme" rel="nofollow">GitHub</a>
<p>""" + ("word " * 250) + """</p>
</body></html>
"""

BAD_PAGE = "<html><head></head><body><img src='x.png'><img src='y.png'></body></html>"


def test_analyzer_extracts_real_seo_signals():
    a = analyze_html("https://acme.com", GOOD_PAGE, status_code=200,
                     final_url="https://acme.com",
                     response_headers={"strict-transport-security": "max-age=1",
                                       "content-security-policy": "default-src 'self'",
                                       "x-frame-options": "DENY",
                                       "x-content-type-options": "nosniff"})
    assert a.title.startswith("Acme CRM")
    assert a.meta_description_length > 100
    assert a.canonical == "https://acme.com/"
    assert a.viewport and a.lang == "en"
    assert a.heading_counts["h1"] == 1 and a.heading_counts["h2"] == 2
    assert a.has_json_ld and "Organization" in a.schema_types
    assert a.open_graph.get("title") == "Acme CRM"
    assert a.twitter_card.get("card") == "summary_large_image"
    assert a.image_count == 2 and a.images_missing_alt == 1
    assert a.internal_links == 2 and a.external_links == 2 and a.nofollow_links == 1
    assert a.social_profiles.get("LinkedIn") and a.social_profiles.get("GitHub")
    assert a.word_count >= 250
    assert a.is_https is True


def test_analyzer_detects_real_technologies():
    a = analyze_html("https://acme.com", GOOD_PAGE)
    # signatures literally present in the HTML → real detections
    assert "Next.js" in a.technologies
    assert "Stripe" in a.technologies


def test_analyzer_flags_real_issues_on_bad_page():
    a = analyze_html("http://bad.example", BAD_PAGE, final_url="http://bad.example")
    codes = {i["code"] for i in a.issues}
    assert "missing_title" in codes
    assert "missing_meta_description" in codes
    assert "missing_h1" in codes
    assert "no_https" in codes           # http:// not https
    assert "images_missing_alt" in codes  # 2 of 2 missing
    assert "missing_viewport" in codes
    # every issue carries severity + fix (Semrush-style)
    for iss in a.issues:
        assert iss["severity"] in ("high", "medium", "low")
        assert iss["fix"] and iss["message"]


def test_health_scores_are_evidence_derived():
    good = analyze_html("https://acme.com", GOOD_PAGE, final_url="https://acme.com",
                        response_headers={h: "1" for h in
                                          ["strict-transport-security", "content-security-policy",
                                           "x-frame-options", "x-content-type-options",
                                           "referrer-policy", "permissions-policy"]})
    bad = analyze_html("http://bad.example", BAD_PAGE, final_url="http://bad.example")
    gs, bs = health_scores(good), health_scores(bad)
    # a clean page must score strictly higher on every dimension than a broken one
    assert gs["overall"] > bs["overall"]
    assert gs["on_page"] > bs["on_page"]
    assert gs["security"] > bs["security"]
    assert all(0 <= v <= 100 for v in gs.values())


async def test_audit_website_endpoint_analyzes_fetched_page(monkeypatch):
    """The /tools/website-audit path analyzes a real fetched page. We patch the
    HTTP fetch (sandbox has no egress) but the ANALYSIS is the real code path."""
    import httpx
    from app.analyzers import website_intel

    class FakeResp:
        status_code = 200
        url = "https://acme.com"
        text = GOOD_PAGE
        headers = {"strict-transport-security": "max-age=1"}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await website_intel.audit_website("acme.com")
    assert result["ok"] is True
    assert result["analysis"]["title"].startswith("Acme CRM")
    assert "Next.js" in result["analysis"]["technologies"]
    assert 0 <= result["scores"]["overall"] <= 100
    assert result["analysis"]["heading_counts"]["h1"] == 1


async def test_audit_website_reports_fetch_failure_honestly(monkeypatch):
    """When the site can't be reached, return ok=False — never fabricated data."""
    import httpx
    from app.analyzers import website_intel

    class BoomClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    result = await website_intel.audit_website("https://nope.invalid")
    assert result["ok"] is False
    assert "Could not fetch" in result["error"]
    assert "analysis" not in result   # no fake analysis on failure


async def test_seo_module_persists_and_lists_history(client, monkeypatch):
    """Full SEO module flow: audit → persist → history → detail, all real."""
    import httpx
    from app.analyzers import website_intel

    class FakeResp:
        status_code = 200; url = "https://acme.com"; text = GOOD_PAGE
        headers = {"strict-transport-security": "max-age=1"}
    class FakeClient:
        def __init__(self,*a,**k): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): return False
        async def get(self,url): return FakeResp()
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    # run audit (persists)
    res = (await client.post("/v2/tools/website-audit", json={"url": "acme.com"})).json()
    assert res["ok"] is True and "audit_id" in res
    assert res["scores"]["overall"] > 0

    # history lists it
    hist = (await client.get("/v2/website-audits")).json()
    assert hist["count"] >= 1
    assert any(a["url"] == "acme.com" for a in hist["audits"])

    # detail returns full analysis
    detail = (await client.get(f"/v2/website-audits/{res['audit_id']}")).json()
    assert detail["url"] == "acme.com"
    assert "analysis" in detail and detail["analysis"]["title"].startswith("Acme CRM")
    assert detail["issue_count"] >= 0


async def test_seo_audit_detail_404(client):
    r = await client.get("/v2/website-audits/nonexistent")
    assert r.status_code == 404
