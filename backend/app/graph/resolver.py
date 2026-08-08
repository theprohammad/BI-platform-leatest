"""S4 — Layered entity resolution (spec §3-S4).

Layers: exact key → alias → fuzzy candidates → scoring bands → decision.
ASYMMETRIC INVARIANT (frozen): a false merge is catastrophic; a missed merge
is only inefficient. Auto-merge requires score ≥ AUTO_MERGE (0.92) AND the
`resolution_auto_merge` flag (default OFF in prod). The 0.70–0.92 band goes to
extract-tier LLM adjudication (budget-capped); adjudication may only CONFIRM
candidates, never propose new ones. Everything ambiguous becomes a
merge-candidate row for the (future UI) review queue.
"""
from rapidfuzz import fuzz

from app.core.config import get_settings
from app.core.logging import get_logger
from app.graph.ontology import Entity, EntityType
from app.providers.llm.base import Tier

log = get_logger("resolver")

AUTO_MERGE = 0.92
ADJUDICATE_FLOOR = 0.70
MAX_ADJUDICATIONS_PER_RUN = 5

_ADJUDICATE_PROMPT = """Are these two names the same real-world organization?
Consider abbreviations, "The" prefixes, and campus/location suffixes.
A: "{a}"
B: "{b}"
Return JSON: {{"same": true|false, "confidence": 0.0}}
Answer false unless clearly the same organization."""


_STOPWORDS = {"the", "of", "pvt", "ltd", "ltd.", "(pvt)", "inc", "inc.", "llc"}


def _norm(name: str) -> str:
    tokens = [t.strip(".,()") for t in name.lower().split()]
    return " ".join(t for t in tokens if t and t not in _STOPWORDS)


def name_score(a: str, b: str) -> float:
    """token_sort on stopword-normalized names. Deliberately NOT token_set:
    subset names ("Punjab University" ⊂ "University of Central Punjab") must
    score LOW — a false merge is catastrophic (frozen asymmetric invariant)."""
    return max(fuzz.token_sort_ratio(_norm(a), _norm(b)),
               fuzz.token_sort_ratio(a.lower(), b.lower())) / 100.0


class EntityResolver:
    """Wraps the store's exact/alias resolution with fuzzy matching + merge."""

    def __init__(self) -> None:
        self._adjudications = 0

    async def resolve(self, ctx, name: str, type_: EntityType) -> Entity:
        graph = ctx.graph
        settings = get_settings()

        # Layer 1+2: exact key / alias / tombstone (store-level)
        entity = await graph.resolve_entity(ctx.workspace_id, name, type_)
        # resolve_entity get-or-creates; detect whether we just created a fresh
        # entity that fuzzy-matches an existing one.
        candidates = await graph.list_entities(
            ctx.workspace_id, type_=type_.value if type_ != EntityType.OTHER else None)
        best, best_score = None, 0.0
        for cand in candidates:
            if cand.id == entity.id:
                continue
            score = max(name_score(name, cand.name),
                        *[name_score(name, al) for al in cand.aliases] or [0.0])
            if score > best_score:
                best, best_score = cand, score

        if best is None or best_score < ADJUDICATE_FLOOR:
            return entity

        method = None
        if best_score >= AUTO_MERGE:
            method = "auto"
        elif self._adjudications < MAX_ADJUDICATIONS_PER_RUN:
            self._adjudications += 1
            try:
                verdict = await ctx.llm.complete_json(
                    _ADJUDICATE_PROMPT.format(a=name, b=best.name),
                    tier=Tier.EXTRACT, label="resolve_adjudicate")
                if verdict.get("same") is True and float(verdict.get("confidence", 0)) >= 0.8:
                    method = "adjudicated"
            except Exception as exc:
                log.info("adjudication failed open (no merge): %s", exc)

        if method and settings.resolution_auto_merge:
            # merge the FRESH entity (fewest claims) into the ESTABLISHED one
            await graph.merge_entities(ctx.workspace_id, loser_id=entity.id,
                                       winner_id=best.id, score=best_score,
                                       method=method)
            log.info("merged '%s' -> '%s' (%.2f, %s)", name, best.name, best_score, method)
            return best
        await graph.record_merge_candidate(ctx.workspace_id, entity.id, best.id, best_score)
        return entity
