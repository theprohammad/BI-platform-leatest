"""The run orchestrator.

Guarantees (Phase 0 contract):
- every agent goes through BaseAgent.execute() → one failure never kills a run
- true parallelism: all LLM/search/fetch calls are async
- partial results: whatever succeeded is returned with per-agent status
- reproducibility: manifest + cost ledger + event log attached to every run
"""
import asyncio

from app.agents.audit_agent import AuditAgent
from app.agents.competitor_agent import CompetitorAgent
from app.agents.lead_agent import LeadAgent
from app.agents.market_agent import MarketAgent
from app.agents.opportunity_agent import OpportunityAgent
from app.agents.outreach_agent import OutreachAgent
from app.agents.pricing_agent import PricingAgent
from app.core.events import Event, bus
from app.core.logging import get_logger
from app.core.versions import run_manifest
from app.orchestrator.intelligence_pipeline import IntelligencePipeline
from app.run.context import RunContext

log = get_logger("pipeline")


class AnalysisPipeline:
    def __init__(self) -> None:
        self.intelligence = IntelligencePipeline()
        self.market = MarketAgent()
        self.competitor = CompetitorAgent()
        self.lead = LeadAgent()
        self.audit = AuditAgent()
        self.pricing = PricingAgent()
        self.opportunity = OpportunityAgent()
        self.outreach = OutreachAgent()

    async def run(self, ctx: RunContext) -> dict:
        await bus.publish(Event("run.started", ctx.run_id,
                                {"company": ctx.request.company_name}))

        # ---- Phase A: research -------------------------------------------
        intel = await self.intelligence.run(ctx)
        shared = intel["shared_intelligence"]
        agents_status: dict[str, dict] = {}

        if intel["status"] != "completed":
            await bus.publish(Event("run.failed", ctx.run_id, {"stage": "research"}))
            return self._result(ctx, intel, agents_status, {}, degraded=True)

        # ---- Phase B: specialists in (real) parallel ----------------------
        envelopes = await asyncio.gather(
            self.market.execute(ctx, intelligence=shared),
            self.competitor.execute(ctx, intelligence=shared),
            self.lead.execute(ctx, intelligence=shared),
            self.audit.execute(ctx),
            self.pricing.execute(ctx, intelligence=shared),
        )
        outputs: dict[str, object] = {}
        for env in envelopes:
            agents_status[env["agent_key"]] = self._status(env)
            outputs[env["agent_key"]] = env["data"]

        # ---- Phase C: synthesis over whatever succeeded --------------------
        opportunity_env = await self.opportunity.execute(
            ctx,
            market=outputs.get("market"),
            competitors=outputs.get("competitor"),
            leads=outputs.get("lead"),
            audit=outputs.get("audit"),
            pricing=outputs.get("pricing"),
        )
        agents_status["opportunity"] = self._status(opportunity_env)
        outputs["opportunity"] = opportunity_env["data"]

        if opportunity_env["status"] == "completed":
            outreach_env = await self.outreach.execute(ctx, opportunity=opportunity_env["data"])
            agents_status["outreach"] = self._status(outreach_env)
            outputs["outreach"] = outreach_env["data"]
        else:
            agents_status["outreach"] = {"status": "skipped",
                                         "reason": "opportunity synthesis failed"}
            outputs["outreach"] = None

        degraded = any(s.get("status") != "completed" for s in agents_status.values())
        await bus.publish(Event("run.completed", ctx.run_id, {"degraded": degraded}))
        return self._result(ctx, intel, agents_status, outputs, degraded=degraded)

    @staticmethod
    def _status(env: dict) -> dict:
        s = {"status": env["status"], "execution_time": env["execution_time"],
             "agent_version": env["agent_version"]}
        if env.get("error"):
            s["error"] = env["error"]
        return s

    @staticmethod
    def _result(ctx: RunContext, intel: dict, agents_status: dict,
                outputs: dict, *, degraded: bool) -> dict:
        return {
            # backward-compatible payload keys (frontend contract preserved)
            "intelligence": {
                "search_plan": intel.get("search_plan"),
                "shared_intelligence": intel.get("shared_intelligence"),
            },
            "market": outputs.get("market"),
            "competitors": outputs.get("competitor"),
            "leads": outputs.get("lead"),
            "audit": outputs.get("audit"),
            "pricing": outputs.get("pricing"),
            "opportunity": outputs.get("opportunity"),
            "outreach": outputs.get("outreach"),
            # new run metadata (rule 2 + observability)
            "meta": {
                "run_id": ctx.run_id,
                "degraded": degraded,
                "agents": agents_status,
                "manifest": run_manifest(),
                "costs": ctx.ledger.summary(),
                "events": bus.run_events(ctx.run_id),
            },
        }
