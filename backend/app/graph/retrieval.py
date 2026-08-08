"""S5 — Hybrid retrieval: FTS ∥ vector ∥ graph-traversal → RRF → trust rerank.
Architecture frozen by owner; internals free.

Leg isolation: any leg failing degrades fusion to the remaining legs; empty
fusion falls back to the keyword scorer. `search_claims`'s public signature is
unchanged (rule 4) — the store delegates here when retrieval_strategy=hybrid.
"""
from app.core.config import get_settings
from app.core.logging import get_logger
from app.graph.embeddings import build_embedder, cosine

log = get_logger("retrieval")

RRF_K = 60
TRUST_LAMBDA = 0.5


class HybridRetriever:
    def __init__(self, graph) -> None:
        self._graph = graph
        self._embedder = build_embedder()

    async def search(self, workspace_id: str, query: str, limit: int = 12):
        legs: dict[str, list] = {}
        for name, fn in (("fts", self._leg_fts), ("vector", self._leg_vector),
                         ("traversal", self._leg_traversal)):
            try:
                legs[name] = await fn(workspace_id, query, limit * 3)
            except Exception as exc:
                log.warning("retrieval leg %s failed: %s", name, exc)
                legs[name] = []

        # Reciprocal Rank Fusion
        scores: dict[str, float] = {}
        claims_by_id: dict[str, object] = {}
        for ranked in legs.values():
            for rank, claim in enumerate(ranked):
                claims_by_id[claim.id] = claim
                scores[claim.id] = scores.get(claim.id, 0.0) + 1.0 / (RRF_K + rank + 1)
        if not scores:
            return await self._graph.keyword_search_claims(workspace_id, query, limit)

        reranked = sorted(
            scores.items(),
            key=lambda kv: -(kv[1] + TRUST_LAMBDA * claims_by_id[kv[0]].trust.confidence
                             / RRF_K))
        return [claims_by_id[cid] for cid, _ in reranked[:limit]]

    # ---- legs --------------------------------------------------------------
    async def _leg_fts(self, workspace_id: str, query: str, k: int):
        """Postgres: tsvector (TODO(prod): GIN index migration when pg is
        primary). SQLite/dev: the tuned keyword scorer serves as the FTS leg."""
        return await self._graph.keyword_search_claims(workspace_id, query, k)

    async def _leg_vector(self, workspace_id: str, query: str, k: int):
        qv = self._embedder.embed([query])[0]
        pool = await self._graph.chunks_with_embeddings(workspace_id)
        scored = sorted(((cosine(qv, emb), ev_id) for ev_id, _text, emb in pool
                         if emb), key=lambda x: -x[0])[: max(k, 20)]
        seen: set[str] = set()
        out = []
        for score, ev_id in scored:
            if score <= 0.05 or ev_id in seen:
                continue
            seen.add(ev_id)
            for claim in await self._graph.claims_citing_evidence(ev_id):
                if claim.status == "active" and claim.workspace_id == workspace_id \
                        and claim.id not in {c.id for c in out}:
                    out.append(claim)
            if len(out) >= k:
                break
        return out[:k]

    async def _leg_traversal(self, workspace_id: str, query: str, k: int):
        entities = await self._graph.list_entities(workspace_id)
        ql = query.lower()
        hits = [e for e in entities
                if e.name.lower() in ql
                or any(a.lower() in ql for a in e.aliases)]
        out = []
        for ent in hits[:4]:
            out.extend(await self._graph.claims(workspace_id,
                                                subject_entity_id=ent.id, limit=k))
            for edge in await self._graph.edges_from(ent.id):
                out.extend(await self._graph.claims(
                    workspace_id, subject_entity_id=edge.target_entity_id, limit=5))
        dedup = {c.id: c for c in out}
        return list(dedup.values())[:k]
