from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.db.session import persist_run
from app.core.versions import PLATFORM_VERSION, run_manifest
from app.orchestrator.analysis_pipeline import AnalysisPipeline
from app.providers.llm.router import build_provider
from app.providers.search.tavily_provider import build_search_provider
from app.run.context import build_run_context
from app.schemas.request import AnalysisRequest
from app.schemas.response import AnalysisResponse

log = get_logger("api")
router = APIRouter()
_pipeline = AnalysisPipeline()


@router.get("/")
async def root():
    return {"message": "Sentient Intelligence API", "version": PLATFORM_VERSION}


@router.get("/health")
async def health():
    return {"status": "healthy", "version": PLATFORM_VERSION}


@router.get("/version")
async def version():
    return run_manifest()


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest):
    ctx = build_run_context(request, build_provider(), build_search_provider())
    log.info("run_id=%s analyze company=%s", ctx.run_id, request.company_name)
    try:
        results = await _pipeline.run(ctx)
    except Exception as exc:  # last-resort guard; agents already isolate
        log.exception("run_id=%s pipeline crashed", ctx.run_id)
        raise HTTPException(status_code=500, detail=f"run {ctx.run_id} failed") from exc

    await persist_run(ctx, results)
    degraded = results["meta"]["degraded"]
    return AnalysisResponse(
        success=True,
        message="Analysis complete" + (" (partial — some agents failed)" if degraded else ""),
        data=results,
    )
