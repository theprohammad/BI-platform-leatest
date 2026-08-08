"""Predicate classification + value normalization (Phase 2.5, D1/D2).

FUNCTIONAL predicates hold ONE current value per subject → conflicts may
supersede/dispute. MULTI_VALUED predicates accumulate values → different
values are never conflicts. UNKNOWN predicates default to MULTI_VALUED:
an unclassified predicate can never destroy data (asymmetric invariant).

normalize_value() is versioned (VALUE_NORMALIZER_VERSION): identity depends
on it, so any change requires a version bump + identity migration (rule 2).
v1 is deliberately conservative — under-normalizing splits corroboration
(recoverable); over-normalizing merges different facts (catastrophic).
"""
import re

FUNCTIONAL = {
    "founded", "enrollment", "tuition", "ranking", "ceo", "rector",
    "chancellor", "employees", "campus_count", "headquarters", "revenue",
    "funding", "acquired_by", "student_faculty_ratio", "acceptance_rate",
}
MULTI_VALUED = {
    "competitor_of", "offers", "partners_with", "located_in", "part_of",
    "accredited_by", "member_of", "subsidiary",
}


def classify(predicate: str | None) -> str:
    if predicate in FUNCTIONAL:
        return "functional"
    return "multi_valued"   # unknown → destruction-proof default


_APPROX = re.compile(r"^(approximately|approx\.?|about|around|roughly|~|estimated|est\.?)\s+",
                     re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def normalize_value(value: str) -> str:
    v = " ".join(str(value).strip().split())
    v = _APPROX.sub("", v)
    v = _THOUSANDS.sub("", v)          # 25,000 -> 25000
    return v.casefold().rstrip(".")
