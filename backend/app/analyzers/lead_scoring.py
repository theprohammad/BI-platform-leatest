"""Lead scoring (Apollo-class) — evidence-derived, explainable, never random.

The score is built from REAL collected signals only. Every point traces to a
named factor with the evidence behind it, so the UI can show *why* a lead scored
what it did. Missing data lowers confidence rather than inventing a number.

Signal sources (all real):
  * technology fit      — tech stack detected from the site (BuiltWith-style)
  * buying signals      — pricing/enterprise cues, hiring language on site
  * growth signals      — GitHub release activity, content depth
  * ICP match           — industry / employee-range fit against a target ICP
  * digital maturity    — HTTPS, structured data, security posture
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreFactor:
    name: str
    points: int
    max_points: int
    detail: str


@dataclass
class LeadScore:
    score: int                      # 0-100
    band: str                       # priority|hot|warm|cold
    factors: list[ScoreFactor] = field(default_factory=list)
    confidence: float = 0.0         # how much real data backed the score

    def as_dict(self) -> dict:
        return {
            "score": self.score, "band": self.band, "confidence": self.confidence,
            "factors": [f.__dict__ for f in self.factors],
        }


def _band(score: int) -> str:
    if score >= 75:
        return "priority"
    if score >= 55:
        return "hot"
    if score >= 35:
        return "warm"
    return "cold"


# High-intent technologies for a B2B SaaS seller (buying/fit signal).
_INTENT_TECH = {"Stripe", "HubSpot", "Salesforce", "Segment", "Marketo",
                "Intercom", "Drift", "Google Tag Manager"}
_MODERN_TECH = {"React", "Next.js", "Vue.js", "Svelte", "Tailwind CSS"}


def score_lead(enrichment: dict, *, icp: dict | None = None) -> LeadScore:
    """Compute an explainable lead score from real enrichment signals.

    `enrichment` is the collected intelligence for a company (website analysis +
    connector output). `icp` optionally defines the ideal profile
    (industry, employee_range) to match against.
    """
    icp = icp or {}
    factors: list[ScoreFactor] = []
    signals_present = 0
    signals_possible = 5

    site = enrichment.get("website") or {}
    techs = set(site.get("technologies", []) or [])
    github = enrichment.get("github") or {}

    # --- 1. technology fit (max 25) ---
    if techs:
        signals_present += 1
        intent_hits = techs & _INTENT_TECH
        modern_hits = techs & _MODERN_TECH
        pts = min(25, len(intent_hits) * 8 + len(modern_hits) * 3)
        detail = []
        if intent_hits:
            detail.append(f"buying-intent tech: {', '.join(sorted(intent_hits))}")
        if modern_hits:
            detail.append(f"modern stack: {', '.join(sorted(modern_hits))}")
        factors.append(ScoreFactor("Technology fit", pts, 25,
                                   "; ".join(detail) or "stack detected, no strong fit signals"))
    else:
        factors.append(ScoreFactor("Technology fit", 0, 25, "no technology detected"))

    # --- 2. buying signals (max 20): pricing/enterprise presence ---
    plans = set(site.get("plans", []) or [])
    prices = site.get("prices", []) or []
    if plans or prices:
        signals_present += 1
        pts = 0
        detail = []
        if "enterprise" in plans:
            pts += 12
            detail.append("enterprise tier present")
        if prices:
            pts += 6
            detail.append(f"{len(prices)} public price point(s)")
        if plans - {"enterprise"}:
            pts += 2
            detail.append(f"plans: {', '.join(sorted(plans))}")
        factors.append(ScoreFactor("Buying signals", min(20, pts), 20,
                                   "; ".join(detail) or "pricing signals present"))
    else:
        factors.append(ScoreFactor("Buying signals", 0, 20, "no pricing/plan signals found"))

    # --- 3. growth signals (max 20): GitHub release activity + content depth ---
    growth_pts = 0
    growth_detail = []
    if github.get("available") and github.get("release_count", 0) > 0:
        signals_present += 1
        rc = github["release_count"]
        growth_pts += min(12, rc * 2)
        growth_detail.append(f"{rc} recent GitHub release(s)")
    wc = site.get("word_count", 0)
    if wc:
        if wc >= 800:
            growth_pts += 8
            growth_detail.append("substantial site content")
        elif wc >= 300:
            growth_pts += 4
            growth_detail.append("moderate site content")
    if growth_detail:
        factors.append(ScoreFactor("Growth signals", min(20, growth_pts), 20,
                                   "; ".join(growth_detail)))
    else:
        factors.append(ScoreFactor("Growth signals", 0, 20, "no growth signals collected"))

    # --- 4. ICP match (max 20) ---
    icp_pts = 0
    icp_detail = []
    lead_industry = (enrichment.get("industry") or "").lower()
    if icp.get("industry") and lead_industry:
        signals_present += 1
        if icp["industry"].lower() in lead_industry or lead_industry in icp["industry"].lower():
            icp_pts += 12
            icp_detail.append(f"industry match ({enrichment.get('industry')})")
        else:
            icp_detail.append("industry differs from ICP")
    lead_emp = enrichment.get("employee_range")
    if icp.get("employee_range") and lead_emp:
        if icp["employee_range"] == lead_emp:
            icp_pts += 8
            icp_detail.append(f"size match ({lead_emp})")
    if icp_detail:
        factors.append(ScoreFactor("ICP match", min(20, icp_pts), 20, "; ".join(icp_detail)))
    else:
        factors.append(ScoreFactor("ICP match", 0, 20, "no ICP defined or no data to match"))

    # --- 5. digital maturity (max 15) ---
    mat_pts = 0
    mat_detail = []
    if site:
        signals_present += 1
        if site.get("is_https"):
            mat_pts += 5
            mat_detail.append("HTTPS")
        if site.get("has_json_ld"):
            mat_pts += 5
            mat_detail.append("structured data")
        sec = site.get("security_headers") or {}
        present_headers = sum(1 for v in sec.values() if v)
        if present_headers >= 3:
            mat_pts += 5
            mat_detail.append(f"{present_headers} security headers")
    factors.append(ScoreFactor("Digital maturity", min(15, mat_pts), 15,
                               "; ".join(mat_detail) or "limited maturity signals"))

    total = sum(f.points for f in factors)
    total = max(0, min(100, total))
    confidence = round(signals_present / signals_possible, 2)
    return LeadScore(score=total, band=_band(total), factors=factors,
                     confidence=confidence)
