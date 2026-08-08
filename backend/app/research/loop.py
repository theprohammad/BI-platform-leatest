"""The bounded research loop — PLANNER v2 (spec P1–P5).

P1: hypotheses are allocated from QUALITY coverage (confidence, domain
    diversity, staleness, disputes), not claim volume.
P2: exactly ONE bounded replan after the first wave, fed a digest of actual
    findings; ≤⅓ of the search budget is reserved for it. Oscillation is
    impossible by construction.
P3: every hypothesis must include a disconfirming query and target a source
    class absent from the topic's current domain set.
P4: open disputes are mandatory research targets.
P5: search budget envelopes per topic derived from brief objectives; a 20%
    reserve stays unallocated.
All world/graph access via the Tool Layer; loop holds no state (rule 3).
"""
import asyncio
import time

from app.core.config import get_settings
from app.core.events import Event, bus
from app.core.logging import get_logger
from app.graph.ontology import Evidence
from app.graph.trust import domain_of, source_quality
from app.providers.llm.base import Tier
from app.research.extraction import extract
from app.research.verification import verify_claims
from app.tools.registry import BudgetExceeded, ToolContext, registry

log = get_logger("research")

_HYPOTHESIS_PROMPT = """You are the research director for a business intelligence analysis.

Organization: {org}
User objectives: {objectives}

Knowledge quality by topic (claims, mean_confidence 0-1, distinct_domains,
staleness_days, open_disputes, current domains):
{coverage}

Open disputes that MUST be investigated first:
{disputes}

Propose the {n} highest-value research questions. Prioritize: (1) resolving
open disputes, (2) topics relevant to the user's objectives, (3) topics with
LOW mean_confidence or FEW distinct_domains or HIGH staleness — a topic with
many claims but one source or low confidence is NOT well known.

For each question provide 3 queries:
- two evidence-seeking queries,
- one DISCONFIRMING query phrased to find evidence AGAINST the likely answer,
targeting at least one source class not in the topic's current domains
(news, government/regulator, reviews, industry reports).

Return JSON:
{{"hypotheses": [{{"question": "", "topic": "profile|market|competitors|pricing|digital|leads",
                  "queries": ["", "", ""]}}]}}
"""

_REPLAN_PROMPT = """You are the research director reviewing first-wave findings.

Organization: {org}
Findings digest:
{digest}

Remaining budget allows at most {n} follow-up questions (or none). Propose
follow-ups ONLY where the digest shows an unresolved contradiction, an
unanswered original question, or a newly discovered entity that materially
matters. Otherwise return an empty list.

Return JSON: {{"hypotheses": [{{"question":"", "topic":"", "queries":["",""]}}]}}
"""

MIN_PROFILE_CLAIMS = 2  # per-subject profile claims; TODO(phase-3): raise as extraction deepens


class ResearchLoop:
    def __init__(self, *, max_hypotheses: int = 3, verify_cap: int = 40) -> None:
        self.max_hypotheses = max_hypotheses
        self.verify_cap = verify_cap

    async def run(self, ctx: ToolContext, *, brief: dict,
                  root_entity_id: str) -> dict:
        from app.playbooks.registry import get_playbook
        playbook = ctx.playbook or get_playbook(None)
        ctx.playbook = playbook
        self.max_hypotheses = min(self.max_hypotheses, playbook.max_hypotheses)
        self.verify_cap = min(self.verify_cap, playbook.verify_cap)
        org = brief["organization"]
        settings = get_settings()
        started = time.time()
        stats = {"evidence_new": 0, "evidence_reused": 0, "cache_hits": 0,
                 "claims": 0, "edges": 0, "verified_failed": 0,
                 "unverified": 0, "hypotheses": [], "replan_hypotheses": []}

        async def stage(name: str, **payload):
            await bus.publish(Event("research.stage", ctx.run_id,
                                    {"stage": name, **payload}))

        # ---- P5: budget envelopes from objectives --------------------------
        objectives = [o.lower() for o in brief.get("objectives", [])]
        self._apply_envelopes(ctx, objectives)

        # ---- 1. understand (delta-aware) ------------------------------------
        await stage("understand", detail=f"Building profile of {org}")
        coverage = await registry.invoke(ctx, "graph.coverage",
                                         subject_entity_id=root_entity_id)
        all_claims: list[str] = []
        if coverage.get("profile", {}).get("claims", 0) < MIN_PROFILE_CLAIMS:
            all_claims += await self._investigate(
                ctx, org, root_entity_id, "profile",
                [f"{org} official website about", f"{org} overview history founded"],
                stats)
        else:
            await stage("understand", detail="Profile known — delta research", reused=True)

        # ---- 2. hypothesize (P1 quality + P3 falsification + P4 disputes) ---
        await stage("hypothesize")
        coverage = await registry.invoke(ctx, "graph.coverage",
                                         subject_entity_id=root_entity_id)
        disputes = [i for i in await registry.invoke(ctx, "graph.insights", kind="dispute")
                    if i.debate_status != "resolved"]
        raw = await ctx.llm.complete_json(
            _HYPOTHESIS_PROMPT.format(
                org=org, objectives=", ".join(objectives) or "general analysis",
                coverage=self._coverage_text(coverage),
                disputes="\n".join(f"- {d.title}: {d.body[:200]}" for d in disputes) or "none",
                n=self.max_hypotheses),
            tier=Tier.REASON, label="hypothesize")
        hypotheses = self._valid(raw)[: self.max_hypotheses]
        stats["hypotheses"] = [h.get("question", "") for h in hypotheses]
        await stage("hypothesize", hypotheses=stats["hypotheses"])

        # ---- 3. investigate wave 1 (parallel, isolated, budget-bounded) -----
        all_claims += await self._wave(ctx, org, root_entity_id, hypotheses, stats, stage)

        # ---- 4. P2: single bounded replan ------------------------------------
        if settings.planner_mode == "v2":
            digest = await self._digest(ctx, root_entity_id, stats)
            await stage("replan")
            try:
                raw = await ctx.llm.complete_json(
                    _REPLAN_PROMPT.format(org=org, digest=digest,
                                          n=max(1, self.max_hypotheses // 2)),
                    tier=Tier.REASON, label="replan")
                follow_ups = self._valid(raw)[: max(1, self.max_hypotheses // 2)]
            except Exception as exc:
                log.info("replan failed open: %s", exc)
                follow_ups = []
            stats["replan_hypotheses"] = [h.get("question", "") for h in follow_ups]
            if follow_ups:
                await stage("replan", hypotheses=stats["replan_hypotheses"])
                all_claims += await self._wave(ctx, org, root_entity_id,
                                               follow_ups, stats, stage)

        # ---- 5. verify (universal citation check; overflow is MARKED) --------
        await stage("verify", claims=len(all_claims))
        to_verify = all_claims[: self.verify_cap]
        outcome = await verify_claims(ctx, to_verify)
        stats["verified_failed"] = len(outcome["failed"])
        stats["unverified"] = max(0, len(all_claims) - self.verify_cap)  # B4 fix: visible

        # ---- 6. reconciliation sweep (B6: parallel-write blind spot) ----------
        from app.graph.diff import reconcile
        stats["reconciled"] = await reconcile(ctx, root_entity_id)

        # ---- 7. specialist swarm (playbook-selected, run concurrently) --------
        # Specialists are independent (each reads the shared graph and writes its
        # own insights), so we run them concurrently. The global LLM queue caps
        # upstream concurrency, so parallelism here shortens wall-clock time
        # without risking a 429 storm. Failure is isolated per specialist.
        from app.agents.specialists import SPECIALISTS
        selected = [(k, SPECIALISTS[k]) for k in playbook.specialists
                    if k in SPECIALISTS]
        for missing in [k for k in playbook.specialists if k not in SPECIALISTS]:
            log.warning("playbook %s names unknown specialist %s", playbook.id, missing)
        await stage("synthesize", specialists=[k for k, _ in selected])

        async def _run_specialist(key, specialist):
            try:
                return await specialist.run(ctx, root_entity_id=root_entity_id,
                                            organization=org)
            except Exception as exc:  # noqa: BLE001 - isolate one specialist's failure
                log.warning("specialist %s failed: %s", key, exc)
                return []

        insight_ids: list[str] = []
        results = await asyncio.gather(
            *[_run_specialist(k, sp) for k, sp in selected])
        for r in results:
            insight_ids += r

        # ---- 8. critic: review insights, adjudicate disputes -------------------
        from app.agents.critic import Critic
        critic = Critic()
        if playbook.review_insights and insight_ids:
            await stage("debate", reviewing=len(insight_ids))
            stats["review"] = await critic.review_insights(ctx, insight_ids)
        if playbook.adjudicate_disputes:
            await stage("adjudicate")
            stats["adjudication"] = await critic.adjudicate_disputes(ctx)

        # ---- 9. recommendations (rule 5 chain end) ------------------------------
        if playbook.recommend:
            from app.agents.recommender import Recommender
            await stage("recommend")
            recs = await Recommender().run(ctx, organization=org)
            stats["recommendations"] = len(recs)
            insight_ids += recs

        stats["playbook"] = {"id": playbook.id, "version": playbook.version}
        stats["claims"] = len(set(all_claims)) - stats["verified_failed"]
        stats["seconds"] = round(time.time() - started, 1)
        stats["insights"] = insight_ids
        stats["searches"] = ctx.budget.used_searches
        await bus.publish(Event("research.done", ctx.run_id,
                                {k: v for k, v in stats.items() if k != "insights"}))
        return stats

    # ---- helpers -------------------------------------------------------------
    @staticmethod
    def _valid(raw: dict) -> list[dict]:
        return [h for h in (raw.get("hypotheses") or [])
                if isinstance(h, dict) and h.get("queries")]

    @staticmethod
    def _coverage_text(coverage: dict) -> str:
        if not coverage:
            return "nothing known yet"
        lines = []
        for topic, q in coverage.items():
            lines.append(f"- {topic}: {q['claims']} claims, conf {q['mean_confidence']}, "
                         f"{q['distinct_domains']} domains, {q['staleness_days']:.0f}d stale, "
                         f"{q['open_disputes']} disputes, sources: {', '.join(q['domains'][:4]) or '-'}")
        return "\n".join(lines)

    def _apply_envelopes(self, ctx: ToolContext, objectives: list[str]) -> None:
        """P5: named objectives get ≥60% of searches; 20% stays reserved."""
        total = ctx.budget.max_searches
        topics = {"competitors": ["competitor"], "pricing": ["pricing", "tuition", "fees"],
                  "market": ["market", "admission"], "digital": ["digital", "seo", "social"],
                  "leads": ["lead"]}
        named = [t for t, kws in topics.items()
                 if any(kw in obj for obj in objectives for kw in kws)]
        if not named:
            return
        share = int(total * 0.6 / len(named))
        others = int(total * 0.2 / max(1, len(topics) - len(named)))
        ctx.budget.topic_envelopes = {
            t: (share if t in named else others) for t in topics}
        # profile & reserve remain un-enveloped (the mandated 20% reserve)

    async def _wave(self, ctx, org, root_entity_id, hypotheses, stats, stage) -> list[str]:
        async def one(h: dict) -> list[str]:
            topic = h.get("topic", "general")
            await stage("investigate", question=h.get("question", ""), topic=topic)
            try:
                return await self._investigate(ctx, org, root_entity_id, topic,
                                               [str(q) for q in h["queries"][:3]],
                                               stats)
            except BudgetExceeded as exc:
                await stage("investigate", topic=topic, stopped=str(exc))
                return []
            except Exception as exc:      # B4 fix: per-hypothesis isolation
                log.warning("run_id=%s hypothesis failed (%s): %s",
                            ctx.run_id, topic, exc)
                await stage("investigate", topic=topic, failed=str(exc))
                return []

        results = await asyncio.gather(*(one(h) for h in hypotheses))
        return [cid for r in results for cid in r]

    async def _digest(self, ctx, root_entity_id: str, stats: dict) -> str:
        coverage = await registry.invoke(ctx, "graph.coverage",
                                         subject_entity_id=root_entity_id)
        disputes = [i for i in await registry.invoke(ctx, "graph.insights", kind="dispute")
                    if i.debate_status != "resolved"]
        parts = [f"Coverage after wave 1:\n{self._coverage_text(coverage)}"]
        if disputes:
            parts.append("Unresolved contradictions:\n" +
                         "\n".join(f"- {d.title}" for d in disputes[:5]))
        parts.append(f"Original questions: {stats['hypotheses']}")
        parts.append(f"Budget used: {ctx.budget.used_searches}/{ctx.budget.max_searches} searches")
        return "\n\n".join(parts)

    async def _investigate(self, ctx: ToolContext, org: str, root_entity_id: str,
                           topic: str, queries: list[str], stats: dict) -> list[str]:
        evidence: list[Evidence] = []
        seen: set[str] = set()
        for query in queries:
            results = await registry.invoke(ctx, "web.search", query=query,
                                            max_results=5, topic=topic)
            for r in results:
                if not r.content or len(r.content) < 80:
                    continue
                out = await registry.invoke(ctx, "graph.ingest_evidence",
                                            url=r.url, title=r.title,
                                            content=r.content,
                                            published_date=r.published_date)
                stats["evidence_new" if out["created"] else "evidence_reused"] += 1
                if out["evidence_id"] not in seen:
                    seen.add(out["evidence_id"])
                    domain = domain_of(r.url)
                    evidence.append(Evidence(
                        id=out["evidence_id"], url=r.url,
                        canonical_url=r.url.rstrip("/"), domain=domain,
                        title=r.title, content=r.content,
                        published_date=r.published_date,
                        quality_score=source_quality(domain)))

        result = await extract(ctx, subject_name=org,
                               subject_entity_id=root_entity_id,
                               topic=topic, evidence=evidence[:10])
        stats["edges"] += len(result["edges"])
        stats["cache_hits"] += result.get("cache_hits", 0)
        await bus.publish(Event("research.extracted", ctx.run_id,
                                {"topic": topic, **result["raw_counts"]}))
        return result["claims"]
