"""Deterministic trust computation — never LLM-assigned (Blueprint §1.1/13).

Same evidence in → same trust out (reproducibility, rule 2). Domain tiers are
data; adjust via review, not vibes.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.graph.ontology import Evidence, TrustVector

_TIER_HIGH = (".gov", ".edu", ".ac.", "reuters.com", "bloomberg.com", "ft.com",
              "wsj.com", "nytimes.com", "bbc.", "economist.com", "gartner.com")
_TIER_LOW = ("blogspot.", "medium.com", "quora.com", "reddit.com", "pinterest.")


def source_quality(domain: str) -> float:
    d = domain.lower()
    if any(t in d for t in _TIER_HIGH):
        return 0.9
    if any(t in d for t in _TIER_LOW):
        return 0.35
    return 0.6


def _freshness(published: str | None, retrieved: str) -> float:
    ref = published or retrieved
    try:
        dt = datetime.fromisoformat(ref.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, AttributeError):
        return 0.4  # unknown date → neutral-low
    if age_days <= 90:
        return 1.0
    if age_days <= 365:
        return 0.8
    if age_days <= 3 * 365:
        return 0.55
    return 0.3


def compute_trust(evidence: list[Evidence]) -> TrustVector:
    if not evidence:
        return TrustVector()
    qualities = [source_quality(e.domain) for e in evidence]
    freshnesses = [_freshness(e.published_date, e.retrieved_at) for e in evidence]
    domains = {e.domain for e in evidence}
    sq = sum(qualities) / len(qualities)
    fr = sum(freshnesses) / len(freshnesses)
    corroboration = min(1.0, (len(domains) - 1) / 2)  # 1 dom=0, 2=.5, 3+=1
    count_factor = min(1.0, len(evidence) / 3)
    confidence = round(0.45 * sq + 0.2 * fr + 0.2 * corroboration + 0.15 * count_factor, 3)
    return TrustVector(
        confidence=confidence,
        source_quality=round(sq, 3),
        evidence_count=len(evidence),
        freshness=round(fr, 3),
        corroboration=round(corroboration, 3),
    )


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def trust_at_read(stored: dict, as_of: str | None, created_at: str | None) -> TrustVector:
    """B9: freshness (and thus confidence) rot with time, so they are derived
    at READ time from the claim's dates. Stable dims come from storage."""
    sq = stored.get("source_quality", 0.0)
    corr = stored.get("corroboration", 0.0)
    count = stored.get("evidence_count", 0)
    fr = _freshness(as_of, created_at or "")
    confidence = round(0.45 * sq + 0.2 * fr + 0.2 * corr
                       + 0.15 * min(1.0, count / 3), 3)
    return TrustVector(confidence=confidence, source_quality=sq,
                       evidence_count=count, freshness=round(fr, 3),
                       corroboration=corr,
                       reasoning_quality=stored.get("reasoning_quality"))
