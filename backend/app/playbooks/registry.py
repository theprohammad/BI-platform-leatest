"""Phase 3 — Playbooks: named, versioned research programs as DATA.

A playbook owns the research posture: objectives, hypothesis/verify budgets,
which specialists run, extra watched predicates for the diff engine, and
refresh thresholds. Code stays generic; product behavior lives here.
Playbook id+version are stamped into the run manifest (rule 2).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlaybookSpec:
    id: str
    version: str
    description: str
    objectives: list = field(default_factory=list)     # planner objective seeds
    max_hypotheses: int = 3
    max_searches: int = 20
    max_llm_calls: int = 60
    verify_cap: int = 40
    specialists: tuple = ("competitor_specialist",)
    watched_predicates: frozenset = frozenset()        # extends diff WATCHED set
    adjudicate_disputes: bool = True
    review_insights: bool = True
    recommend: bool = True
    refresh_staleness_days: float | None = None        # None → global default
    # When True, the run also performs cross-module enrichment after research:
    # website audit, monitoring baselines, and a CRM/lead profile. This is what
    # makes "Executive Intelligence" a genuinely complete investigation instead
    # of research only. Each step is best-effort and never fabricates.
    full_investigation: bool = False


_PLAYBOOKS = {
    "full_analysis": PlaybookSpec(
        id="full_analysis", version="1.0.0",
        description="Complete organization investigation: research, all "
                    "specialists, validation, recommendations, website audit, "
                    "monitoring baselines and CRM profile.",
        specialists=("competitor_specialist", "market_specialist",
                     "pricing_specialist"),
        full_investigation=True,
    ),
    "competitor_scan": PlaybookSpec(
        id="competitor_scan", version="1.0.0",
        description="Competitor-focused sweep with tighter budgets.",
        objectives=["identify and profile competitors"],
        max_hypotheses=2, max_searches=12,
        specialists=("competitor_specialist",),
        watched_predicates=frozenset({"offers", "partners_with"}),
    ),
    "pricing_watch": PlaybookSpec(
        id="pricing_watch", version="1.0.0",
        description="Pricing intelligence with aggressive freshness.",
        objectives=["pricing and tuition intelligence"],
        max_hypotheses=2, max_searches=10,
        specialists=("pricing_specialist",),
        watched_predicates=frozenset({"tuition", "pricing", "discount"}),
        refresh_staleness_days=7.0,
    ),
}
DEFAULT_PLAYBOOK = "full_analysis"


def get_playbook(playbook_id: str | None) -> PlaybookSpec:
    if not playbook_id:
        return _PLAYBOOKS[DEFAULT_PLAYBOOK]
    if playbook_id not in _PLAYBOOKS:
        raise ValueError(f"unknown playbook '{playbook_id}'; "
                         f"available: {sorted(_PLAYBOOKS)}")
    return _PLAYBOOKS[playbook_id]


def list_playbooks() -> list[dict]:
    return [{"id": p.id, "version": p.version, "description": p.description,
             "specialists": list(p.specialists),
             "full_investigation": p.full_investigation}
            for p in _PLAYBOOKS.values()]
