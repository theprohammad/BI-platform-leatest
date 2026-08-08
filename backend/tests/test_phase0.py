import pytest

from app.core.ledger import CostLedger
from app.orchestrator.analysis_pipeline import AnalysisPipeline
from app.providers.llm.router import LLMRouter
from app.run.context import RunContext
from app.schemas.plan import SearchPlan
from tests.fakes import FakeLLM, FakeSearch


class Req:
    company_name = "Acme University"
    website = "https://example.edu"
    industry = "Higher Education"
    target_market = "Pakistan"

    def model_dump(self, **k):
        return {"company_name": self.company_name}


def ctx_with(llm: FakeLLM) -> RunContext:
    ledger = CostLedger()
    return RunContext(request=Req(), llm=LLMRouter(llm, ledger=ledger, run_id="test"),
                      search=FakeSearch(), ledger=ledger, run_id="test")


def test_search_plan_validation_coerces_garbage():
    plan = SearchPlan.model_validate({"market": "single string", "bogus_key": ["x"],
                                      "competitors": None, "leads": [1, 2]})
    assert plan.market == ["single string"]
    assert plan.competitors == []
    assert plan.leads == ["1", "2"]


@pytest.mark.asyncio
async def test_partial_failure_returns_other_agents(monkeypatch):
    async def fake_site(url):
        return {"title": "x", "status_code": 200}
    monkeypatch.setattr("app.agents.audit_agent.analyze_website", fake_site)

    pipeline = AnalysisPipeline()
    result = await pipeline.run(ctx_with(FakeLLM(fail_labels={"market"})))

    meta = result["meta"]
    assert meta["degraded"] is True
    assert meta["agents"]["market"]["status"] == "failed"
    assert meta["agents"]["competitor"]["status"] == "completed"
    assert result["competitors"] == {"agent": "competitor", "ok": True}
    assert result["market"] is None
    assert result["opportunity"] is not None          # synthesis still ran
    assert meta["manifest"]["agent_versions"]["market"]  # rule 2 stamp present
    assert meta["costs"]["llm_calls"] > 0


@pytest.mark.asyncio
async def test_json_repair_retry(monkeypatch):
    async def fake_site(url):
        return {"title": "x"}
    monkeypatch.setattr("app.agents.audit_agent.analyze_website", fake_site)

    llm = FakeLLM(bad_json_labels={"pricing"})
    result = await AnalysisPipeline().run(ctx_with(llm))
    assert result["meta"]["agents"]["pricing"]["status"] == "completed"
    assert llm.calls.count("pricing") == 2  # first invalid, one repair


@pytest.mark.asyncio
async def test_planner_failure_degrades_gracefully():
    result = await AnalysisPipeline().run(ctx_with(FakeLLM(fail_labels={"search_planner"})))
    assert result["meta"]["degraded"] is True
    assert result["market"] is None
    assert result["meta"]["manifest"]["platform_version"].startswith("0.")
