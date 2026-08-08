"""Apollo-class Sales Intelligence — full vertical. Lead scoring is pure &
evidence-derived; the discover→CRM→pipeline flow is tested end-to-end. Contact
emails are never fabricated. AI email uses the real router (scripted in tests)."""
import httpx
import pytest

from app.analyzers.lead_scoring import score_lead


@pytest.fixture
async def client(tmp_path):
    from app.db import session as db
    from app.main import app
    await db.init_db(f"sqlite+aiosqlite:///{tmp_path}/apollo.db", use_alembic=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


STRONG = {
    "industry": "B2B SaaS", "employee_range": "51-200",
    "website": {"technologies": ["React", "Next.js", "Stripe", "HubSpot"],
                "plans": ["free", "pro", "enterprise"], "prices": ["$49/mo", "$99/mo"],
                "word_count": 1200, "is_https": True, "has_json_ld": True,
                "security_headers": {"a": True, "b": True, "c": True}},
    "github": {"available": True, "release_count": 5},
}


def test_lead_scoring_is_evidence_derived_and_explainable():
    s = score_lead(STRONG, icp={"industry": "B2B SaaS", "employee_range": "51-200"})
    assert s.score >= 75 and s.band == "priority"
    assert s.confidence == 1.0
    names = {f.name for f in s.factors}
    assert names == {"Technology fit", "Buying signals", "Growth signals", "ICP match", "Digital maturity"}
    # every factor has a detail explaining the points (no black box)
    for f in s.factors:
        assert 0 <= f.points <= f.max_points and f.detail


def test_weak_lead_scores_low_with_low_confidence():
    s = score_lead({"industry": "", "website": {"technologies": [], "is_https": False}})
    assert s.band == "cold" and s.score < 35
    assert s.confidence < 0.5   # little real data → honest low confidence


def test_scoring_never_exceeds_bounds():
    s = score_lead(STRONG, icp={"industry": "B2B SaaS", "employee_range": "51-200"})
    assert 0 <= s.score <= 100


async def test_full_apollo_flow(client, monkeypatch):
    """discover→enrich→score→CRM (stage/note/task)→sequence→pipeline report."""
    from app.analyzers import website_intel

    PAGE = ("<html lang=en><head><title>Beta — Enterprise CRM</title>"
            "<meta name=description content='The enterprise CRM, from $99/mo'>"
            "<script type='application/ld+json'>{\"@type\":\"Organization\"}</script>"
            "<script src='https://js.stripe.com/v3/'></script>"
            "<div class='__NEXT_DATA__'></div></head>"
            "<body><h1>Enterprise CRM</h1>" + ("word " * 900) +
            "<a href='https://linkedin.com/company/beta'>li</a></body></html>")

    class FakeResp:
        status_code = 200; url = "https://beta.com"; text = PAGE
        headers = {"strict-transport-security": "1"}
    class FakeClient:
        def __init__(self,*a,**k): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): return False
        async def get(self,url): return FakeResp()
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    # discover
    disc = (await client.post("/v2/sales/discover", json={
        "company_name": "Beta", "domain": "beta.com", "industry": "B2B SaaS",
        "employee_range": "51-200", "icp_industry": "B2B SaaS",
        "icp_employee_range": "51-200"})).json()
    assert disc["enrichment_ok"] is True
    assert disc["score"] > 40           # real signals present
    lead_id = disc["lead_id"]

    # lead list + filter by band
    leads = (await client.get("/v2/sales/leads")).json()
    assert leads["count"] == 1

    # detail carries enrichment + score breakdown + activity
    detail = (await client.get(f"/v2/sales/leads/{lead_id}")).json()
    assert detail["company_name"] == "Beta"
    assert detail["score_breakdown"]["factors"]
    assert any(a["kind"] == "enriched" for a in detail["activities"])
    # any discovered contact must be honest about email status
    for c in detail["contacts"]:
        assert c["email"] is None and c["email_status"] == "not_found"

    # CRM: move stage, note, task
    assert (await client.post(f"/v2/sales/leads/{lead_id}/stage", json={"stage": "qualified"})).json()["ok"]
    assert (await client.post(f"/v2/sales/leads/{lead_id}/notes", json={"body": "Great ICP fit"})).json()["ok"]
    tid = (await client.post(f"/v2/sales/leads/{lead_id}/tasks", json={"title": "Email CTO"})).json()["task_id"]
    assert (await client.post(f"/v2/sales/tasks/{tid}/complete")).json()["ok"]

    detail2 = (await client.get(f"/v2/sales/leads/{lead_id}")).json()
    assert detail2["stage"] == "qualified"
    assert len(detail2["notes"]) == 1 and detail2["tasks"][0]["done"] is True
    assert any(a["kind"] == "stage_change" for a in detail2["activities"])

    # sequence scaffold
    seq = (await client.get(f"/v2/sales/leads/{lead_id}/sequence")).json()
    assert len(seq["sequence"]) == 5

    # pipeline report
    pipe = (await client.get("/v2/sales/pipeline")).json()
    assert pipe["has_data"] is True and pipe["total_leads"] == 1
    assert pipe["by_stage"]["qualified"] == 1


async def test_email_generation_uses_real_router(client, monkeypatch):
    """AI email is generated via the LLM router grounded in enrichment. We
    script the provider so no network is needed; the grounding path is real."""
    from app.db import session as db

    # seed a lead directly
    lead_id = await db.create_lead(
        db.DEFAULT_WORKSPACE_ID, company_name="Beta", domain="beta.com",
        industry="B2B SaaS", location=None, employee_range="51-200",
        enrichment={"website": {"meta_description": "Enterprise CRM",
                                "h1": ["Enterprise CRM"], "technologies": ["Stripe"],
                                "plans": ["enterprise"]}},
        score=80, score_band="priority", score_breakdown={})

    import app.api.v2 as v2

    class ScriptedProvider:
        async def complete_json(self, *, model, system, prompt, temperature, timeout):
            from app.providers.llm.base import LLMResult
            import json as _j
            return LLMResult(text=_j.dumps({
                "subject": "Scaling Beta's enterprise CRM",
                "body": "Hi there — noticed Beta positions around enterprise CRM...",
                "personalization_notes": ["enterprise positioning", "Stripe"]}),
                model="test", prompt_tokens=10, completion_tokens=20)
    monkeypatch.setattr(v2, "build_provider", lambda: ScriptedProvider())

    res = (await client.post(f"/v2/sales/leads/{lead_id}/email",
                             json={"kind": "cold"})).json()
    assert res["ok"] is True
    assert res["email"]["subject"]
    assert "enterprise positioning" in res["email"]["personalization_notes"]
    # grounded only in real facts
    assert "Stripe" in res["email"]["grounded_facts"]["technologies"]
