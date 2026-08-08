"""Evidence → Entities/Edges/Claims — EXTRACTION v3 (spec S2+S3).

Changes from v2 (EXTRACTION_VERSION=3, stamped in core/versions.py):
- CHUNKED: full evidence content is used, batched by chunks (~6k-char batches),
  never truncated. C4 identity makes cross-batch duplicate claims merge
  harmlessly — chunking's classic double-extraction problem is pre-solved.
- CACHED: (evidence, subject, topic, version) already extracted → skipped.
  Re-research reads only new content (owner rule 4, measured via ledger).
- PREDICATES: claims carry a normalized structural key where applicable —
  the diff engine's (S7) conflict detection hinges on this.
- RELATIONAL CLAIMS: relationships are emitted as claims; graph.write_edge
  synthesizes the claim-backed edge (C5-B, frozen invariant).
All writes via the Tool Layer (conformance-tested).
"""
import json

from app.core.logging import get_logger
from app.core.versions import EXTRACTION_VERSION
from app.graph.ontology import ClaimKind, EntityType, Evidence
from app.providers.llm.base import Tier
from app.research.chunker import chunk_text
from app.tools.registry import registry

log = get_logger("extraction")

BATCH_CHAR_BUDGET = 6000     # per extract-tier call (≈1.5k tokens of evidence)

_PROMPT = """You are an information extraction engine for a business intelligence graph.

Subject organization: {subject}
Topic: {topic}

Below are numbered evidence excerpts. Extract ONLY what the evidence states.

Return JSON:
{{
  "entities": [{{"name":"", "type":"organization|person|product|location|technology|other"}}],
  "claims": [{{
     "statement":"one atomic factual sentence",
     "kind":"fact|event|metric",
     "subject":"entity name the claim is about (default: the subject organization)",
     "predicate":"snake_case key naming WHAT the claim states (founded, enrollment, tuition, ranking, campus_count, ceo, rector, ...) or null for narrative statements",
     "value":"the value for the predicate (number/amount/name) if any, else null",
     "as_of":"ISO date if the evidence states one, else null",
     "evidence": [1]
  }}],
  "relations": [{{"source":"entity name","relation":"competitor_of|offers|located_in|partners_with|part_of","target":"entity name","evidence":[1]}}]
}}

Rules:
- "evidence" lists the NUMBERS of excerpts that state it. Never cite a number not shown.
- Do not infer, estimate, or add outside knowledge. If evidence is silent, omit.
- Claims must be atomic and specific (names, numbers, dates).
- Use the SAME predicate word for the same kind of fact (enrollment, not students_count).
- kind=event for dated changes (launched, opened, appointed, acquired, raised).

EVIDENCE:
{evidence}
"""


def _batches(evidence: list[Evidence]) -> list[list[tuple[Evidence, str]]]:
    """Chunk every doc, pack (doc, chunk) pairs into ~BATCH_CHAR_BUDGET batches."""
    pairs: list[tuple[Evidence, str]] = []
    for ev in evidence:
        for chunk in chunk_text(ev.content):
            pairs.append((ev, chunk))
    batches, current, size = [], [], 0
    for pair in pairs:
        if current and size + len(pair[1]) > BATCH_CHAR_BUDGET:
            batches.append(current)
            current, size = [], 0
        current.append(pair)
        size += len(pair[1])
    if current:
        batches.append(current)
    return batches


def _render(batch: list[tuple[Evidence, str]]) -> str:
    blocks = []
    for i, (ev, chunk) in enumerate(batch, start=1):
        blocks.append(f"[{i}] {ev.title}\nURL: {ev.url}\n"
                      f"Date: {ev.published_date or 'unknown'}\n{chunk}")
    return "\n\n".join(blocks)


async def extract(ctx, *, subject_name: str, subject_entity_id: str,
                  topic: str, evidence: list[Evidence]) -> dict:
    """Returns {"claims": ids, "entities": ids, "edges": ids, "raw_counts",
    "cache_hits"}."""
    # ---- S3 cache: only extract evidence not yet processed for this key ----
    fresh: list[Evidence] = []
    cache_hits = 0
    for ev in evidence:
        if await ctx.graph.extraction_cached(ev.id, subject_entity_id, topic,
                                             EXTRACTION_VERSION):
            cache_hits += 1
        else:
            fresh.append(ev)
    if not fresh:
        return {"claims": [], "entities": [], "edges": [],
                "raw_counts": {"claims": 0, "edges": 0}, "cache_hits": cache_hits}

    entity_ids: dict[str, str] = {subject_name.strip().lower(): subject_entity_id}
    created_entities: list[str] = []

    async def resolve(name: str, type_hint: str = "other") -> str:
        key = name.strip().lower()
        if key in entity_ids:
            return entity_ids[key]
        try:
            etype = EntityType(type_hint)
        except ValueError:
            etype = EntityType.OTHER
        ent = await registry.invoke(ctx, "graph.resolve_entity", name=name, type=etype)
        entity_ids[key] = ent.id
        created_entities.append(ent.id)
        return ent.id

    claim_ids: list[str] = []
    edge_ids: list[str] = []

    for batch in _batches(fresh):
        raw = await ctx.llm.complete_json(
            _PROMPT.format(subject=subject_name, topic=topic,
                           evidence=_render(batch)),
            tier=Tier.EXTRACT, label=f"extract:{topic}")
        index_to_id = {i + 1: pair[0].id for i, pair in enumerate(batch)}

        for e in raw.get("entities", []) or []:
            if isinstance(e, dict) and e.get("name"):
                await resolve(e["name"], e.get("type", "other"))

        for c in raw.get("claims", []) or []:
            if not isinstance(c, dict) or not c.get("statement"):
                continue
            ev_ids = [index_to_id[i] for i in (c.get("evidence") or [])
                      if i in index_to_id]
            if not ev_ids:
                log.info("dropped unevidenced claim: %.80s", c.get("statement", ""))
                continue
            subject = (c.get("subject") or subject_name).strip()
            subj_id = await resolve(
                subject,
                "organization" if subject.lower() == subject_name.lower() else "other")
            try:
                kind = ClaimKind(c.get("kind", "fact"))
            except ValueError:
                kind = ClaimKind.FACT
            claim_ids.append(await registry.invoke(
                ctx, "graph.write_claim",
                subject_entity_id=subj_id, kind=kind,
                statement=str(c["statement"]).strip(),
                value=(str(c["value"]) if c.get("value") not in (None, "", "null") else None),
                predicate=(c.get("predicate") or None),
                topic=topic, as_of=c.get("as_of"), evidence_ids=ev_ids))

        for e in raw.get("relations", []) or []:
            if not isinstance(e, dict) or not all(e.get(k) for k in ("source", "relation", "target")):
                continue
            ev_ids = [index_to_id[i] for i in (e.get("evidence") or []) if i in index_to_id]
            if not ev_ids:
                continue
            src = await resolve(e["source"], "organization")
            tgt = await resolve(e["target"], "organization")
            if src == tgt:
                continue
            edge_ids.append(await registry.invoke(
                ctx, "graph.write_edge", source_entity_id=src,
                relation=str(e["relation"]).strip(), target_entity_id=tgt,
                evidence_ids=ev_ids))

    for ev in fresh:   # mark cache only after all batches succeeded
        await ctx.graph.mark_extracted(ev.id, subject_entity_id, topic,
                                       EXTRACTION_VERSION)

    claim_ids = list(dict.fromkeys(claim_ids))
    if claim_ids:
        # Lifecycle rule 6: stale re-assertions attach to dead rows and are
        # EXCLUDED from run outputs (one batched read, not per-claim).
        rows = await ctx.graph.get_claims(claim_ids)
        active = {c.id for c in rows if c.status == "active"}
        claim_ids = [cid for cid in claim_ids if cid in active]
    return {"claims": claim_ids, "entities": created_entities, "edges": edge_ids,
            "raw_counts": {"claims": len(claim_ids), "edges": len(edge_ids)},
            "cache_hits": cache_hits}


def parse_extraction_json(text: str) -> dict:
    return json.loads(text)
