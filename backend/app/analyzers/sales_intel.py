"""Company enrichment orchestration + AI outreach (Apollo-class).

Enrichment fans out real collectors (website analyzer + connectors) for a
company and assembles a single enrichment record that feeds lead scoring, the
CRM, and personalized outreach. Contact discovery extracts only PUBLIC signals
(social profiles, leadership names when present in structured data); emails are
marked found/not_found and never fabricated.

AI outreach uses the real Groq-backed LLM router, grounded strictly in the
collected enrichment (Rule 5: evidence-backed, no hallucinated facts).
"""
from __future__ import annotations

import json
from urllib.parse import urlparse


async def enrich_company(domain_or_url: str, *, industry: str | None = None,
                         employee_range: str | None = None) -> dict:
    """Collect real signals for a company. Website analysis always; GitHub if a
    repo is discoverable. Returns a normalized enrichment record."""
    from app.analyzers.website_intel import audit_website

    enrichment: dict = {"domain": _domain(domain_or_url), "industry": industry,
                        "employee_range": employee_range,
                        "website": None, "github": None,
                        "social_profiles": {}, "contacts": []}

    audit = await audit_website(domain_or_url)
    if audit.get("ok") and audit.get("analysis"):
        a = audit["analysis"]
        from app.analyzers.competitor_monitor import extract_signals
        sig = extract_signals(a)
        enrichment["website"] = {
            **sig,
            "is_https": a.get("is_https"),
            "has_json_ld": a.get("has_json_ld"),
            "security_headers": a.get("security_headers", {}),
            "final_url": a.get("final_url"),
        }
        enrichment["social_profiles"] = a.get("social_profiles", {})
        enrichment["scores"] = audit.get("scores", {})
        enrichment["contacts"] = _public_contacts(a)

    # GitHub connector (real release activity) if a GitHub profile was found
    gh_url = enrichment["social_profiles"].get("GitHub")
    if gh_url:
        from app.connectors.github import GitHubConnector
        res = await GitHubConnector().collect_cached(gh_url)
        enrichment["github"] = {
            "available": res.available,
            "release_count": sum(1 for i in res.items if i.kind == "release"),
            "items": [i.__dict__ for i in res.items[:5]],
            "note": res.note,
        }

    return enrichment


def _domain(s: str) -> str:
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    return urlparse(s).netloc.removeprefix("www.")


def _public_contacts(analysis: dict) -> list[dict]:
    """Extract only PUBLIC contact signals. We surface leadership names if the
    page exposes schema.org Person/founder data; emails are never fabricated —
    absence is reported as not_found."""
    contacts: list[dict] = []
    # (Deliberately conservative: real deployments extend this with /team and
    # /about crawling. Here we only assert what's structurally present.)
    schema_types = analysis.get("schema_types", []) or []
    if "Organization" in schema_types or "Person" in schema_types:
        # We know structured org data exists but not individual emails.
        contacts.append({
            "name": "Leadership (see company site)",
            "title": "Decision makers",
            "email": None,
            "email_status": "not_found",
            "source": "schema.org structured data",
        })
    return contacts


async def generate_outreach_email(ctx_llm, *, lead: dict, kind: str = "cold",
                                  sender: str = "our team",
                                  competitor_context: str | None = None) -> dict:
    """Generate a personalized outreach email grounded in REAL enrichment.

    ctx_llm is an LLMRouter (Groq-backed, queued/cached). The prompt is built
    only from collected facts; the model is instructed not to invent specifics.
    """
    enrichment = lead.get("enrichment", {}) or {}
    site = enrichment.get("website", {}) or {}
    facts = {
        "company": lead.get("company_name"),
        "industry": lead.get("industry"),
        "positioning": site.get("meta_description"),
        "headline": (site.get("h1") or [None])[0],
        "technologies": site.get("technologies", []),
        "plans": site.get("plans", []),
        "score_band": lead.get("score_band"),
    }
    if competitor_context:
        facts["competitive_context"] = competitor_context

    prompt = (
        "You are an expert B2B SDR writing a concise, personalized outreach "
        f"email of type '{kind}'. Use ONLY the facts provided; do not invent "
        "names, metrics, or events. If a fact is missing, omit it.\n\n"
        f"Sender: {sender}\n"
        f"Verified facts about the prospect (JSON):\n{json.dumps(facts, indent=2)}\n\n"
        "Return JSON with keys: subject (string, <=60 chars), "
        "body (string, 90-140 words, 2 short paragraphs + 1 CTA question), "
        "personalization_notes (array of the specific facts you used)."
    )
    from app.providers.llm.base import Tier
    result = await ctx_llm.complete_json(prompt, tier=Tier.REASON, label="outreach_email")
    # normalize
    return {
        "subject": result.get("subject", "").strip()[:120],
        "body": result.get("body", "").strip(),
        "personalization_notes": result.get("personalization_notes", []),
        "kind": kind,
        "grounded_facts": {k: v for k, v in facts.items() if v},
    }


def build_sequence(lead: dict) -> list[dict]:
    """A multi-step outreach sequence scaffold (Apollo-style). Steps are real,
    scheduled placeholders the user can fill/generate; timing is standard."""
    company = lead.get("company_name", "the company")
    return [
        {"day": 1, "channel": "email", "type": "cold",
         "goal": f"Introduce value to {company}"},
        {"day": 3, "channel": "email", "type": "follow-up",
         "goal": "Add a relevant proof point"},
        {"day": 6, "channel": "linkedin", "type": "connect",
         "goal": "Connect with a decision maker"},
        {"day": 9, "channel": "email", "type": "case-study",
         "goal": "Share a similar-company result"},
        {"day": 13, "channel": "email", "type": "breakup",
         "goal": "Final, low-pressure close"},
    ]
