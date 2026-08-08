"""Reproducibility registry (non-negotiable rule 2).

Every analysis records the exact versions of everything that shaped it:
graph schema, agents, prompts/playbooks, models, extraction logic.
Bump a version whenever behavior changes. The manifest is stamped onto
every run response and persisted with the run.
"""
from datetime import datetime, timezone

from app.core.config import get_settings

PLATFORM_VERSION = "0.6.0-phase3"   # critic, swarm, playbooks, recommendations
GRAPH_SCHEMA_VERSION = "3.2"        # 3: claims.value_entity_id (additive)
EXTRACTION_VERSION = "3"            # 2: chunked, cached, predicates, relational claims
PROMPT_PACK_VERSION = "3.0.0"       # critic, reviewer, swarm frames, recommender
PLAYBOOK_VERSION = "1"              # app/playbooks/registry.py
CLAIM_IDENTITY_VERSION = "2"        # predicate+value identity (Phase 2.5)
VALUE_NORMALIZER_VERSION = "1"      # graph/predicates.py — identity depends on it

AGENT_VERSIONS: dict[str, str] = {
    "search_planner": "1.1.0",      # 1.1: validated SearchPlan output
    "research_summarizer": "1.0.0",
    "market": "1.1.0",              # 1.1: async, isolated, validated access
    "competitor": "1.1.0",
    "lead": "1.1.0",
    "audit": "1.1.0",               # 1.1: non-blocking fetch
    "pricing": "1.1.0",
    "opportunity": "1.1.0",
    "outreach": "1.1.0",
    # v2 (steel thread)
    "intake": "2.0.0",
    "research_loop": "2.0.0",
    "competitor_specialist": "3.0.0",
    "analyst_chat": "2.0.0",
    # phase 2
    "planner": "2.0.0",
    "retrieval": "2.0.0",
    "resolver": "2.0.0",
    "diff_engine": "2.2.0",   # reconcile sweep, playbook watched, value_entity_id
    "critic": "1.0.0",
    "market_specialist": "1.0.0",
    "pricing_specialist": "1.0.0",
    "recommender": "1.0.0",
}


def run_manifest() -> dict:
    s = get_settings()
    return {
        "platform_version": PLATFORM_VERSION,
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "claim_identity_version": CLAIM_IDENTITY_VERSION,
        "value_normalizer_version": VALUE_NORMALIZER_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "prompt_pack_version": PROMPT_PACK_VERSION,
        "playbook_version": PLAYBOOK_VERSION,
        "agent_versions": dict(AGENT_VERSIONS),
        "models": {
            "provider": s.llm_provider,
            "extract": s.model_extract,
            "reason": s.model_reason,
            "judge": s.model_judge,
        },
        "search_provider": s.search_provider,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
