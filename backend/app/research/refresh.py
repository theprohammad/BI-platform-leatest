"""S8 — Monitoring Stage A: "Refresh intelligence".

~90% reuse of existing primitives (frozen invariant: no duplicate storage):
- targeting  → graph.coverage quality vector (stale / weak / disputed topics)
- re-check   → web.fetch of high-fan-in evidence URLs (C3 reverse index);
               unchanged content short-circuits on the content hash
- semantics  → extraction v3 cache + identity merge + S7 diff engine
- output     → change report (S7) + signals already emitted by the diff engine
Stage B (Phase M) adds only a scheduler + monitoring_config.
"""
import time

from app.core.config import get_settings
from app.core.events import Event, bus
from app.core.logging import get_logger
from app.graph.diff import build_change_report
from app.graph.ontology import Evidence
from app.graph.trust import domain_of, source_quality
from app.research.extraction import extract
from app.research.loop import ResearchLoop
from app.tools.registry import BudgetExceeded, ToolContext, registry

log = get_logger("refresh")


async def run_refresh(ctx: ToolContext, *, organization: str,
                      root_entity_id: str, since_iso: str) -> dict:
    settings = get_settings()
    started = time.time()
    stats = {"mode": "refresh", "refetched_urls": 0, "unchanged": 0,
             "topics_targeted": [], "evidence_new": 0, "evidence_reused": 0,
             "cache_hits": 0, "edges": 0}

    await bus.publish(Event("research.stage", ctx.run_id,
                            {"stage": "refresh", "detail": "selecting targets"}))

    # ---- Target 1: high-fan-in evidence pages, re-fetched -------------------
    pages = await ctx.graph.high_fanin_evidence(
        ctx.workspace_id, root_entity_id,
        min_claims=settings.refresh_url_fanin_min,
        limit=settings.refresh_url_cap)
    refreshed: list[Evidence] = []
    for page in pages:
        try:
            fetched = await registry.invoke(ctx, "web.fetch", url=page.canonical_url)
        except BudgetExceeded:
            break
        except Exception as exc:
            log.info("refetch failed %s: %s", page.canonical_url, exc)
            continue
        stats["refetched_urls"] += 1
        out = await registry.invoke(ctx, "graph.ingest_evidence",
                                    url=fetched["url"], title=fetched["title"],
                                    content=fetched["text"])
        if out["created"]:
            domain = domain_of(fetched["url"])
            refreshed.append(Evidence(
                id=out["evidence_id"], url=fetched["url"],
                canonical_url=fetched["url"].rstrip("/"), domain=domain,
                title=fetched["title"], content=fetched["text"],
                quality_score=source_quality(domain)))
        else:
            stats["unchanged"] += 1     # content hash identical → nothing to do

    if refreshed:
        result = await extract(ctx, subject_name=organization,
                               subject_entity_id=root_entity_id,
                               topic="profile", evidence=refreshed)
        stats["edges"] += len(result["edges"])
        stats["cache_hits"] += result.get("cache_hits", 0)

    # ---- Target 2: stale / weak / disputed topics via the research loop -----
    coverage = await registry.invoke(ctx, "graph.coverage",
                                     subject_entity_id=root_entity_id)
    targets = [t for t, q in coverage.items()
               if q["staleness_days"] > settings.refresh_staleness_days
               or q["mean_confidence"] < settings.refresh_min_confidence
               or q["open_disputes"] > 0]
    stats["topics_targeted"] = targets
    if targets:
        loop = ResearchLoop(max_hypotheses=min(2, len(targets)))
        loop_stats = await loop.run(
            ctx, brief={"organization": organization,
                        "objectives": [f"update {t}" for t in targets]},
            root_entity_id=root_entity_id)
        for key in ("evidence_new", "evidence_reused", "cache_hits", "edges"):
            stats[key] += loop_stats.get(key, 0)

    stats["change_report"] = await build_change_report(ctx, root_entity_id, since_iso)
    stats["seconds"] = round(time.time() - started, 1)
    stats["searches"] = ctx.budget.used_searches
    await bus.publish(Event("research.done", ctx.run_id,
                            {"mode": "refresh",
                             "changes": stats["change_report"]["new_claims"]}))
    return stats
