from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.v2 import router as v2_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.versions import PLATFORM_VERSION
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    get_logger("app").info("startup version=%s env=%s", PLATFORM_VERSION, settings.environment)
    # Size the LLM request queue from settings (Priority Zero 429 guard).
    from app.core.throttle import configure_llm_queue
    configure_llm_queue(settings.llm_max_concurrent)
    await init_db()
    # Crash recovery + retention (best-effort; never block startup).
    try:
        from app.db.session import prune_events, reap_stale_jobs
        await reap_stale_jobs()
        await prune_events()
    except Exception as exc:  # noqa: BLE001
        get_logger("app").warning("startup maintenance skipped: %s", exc)
    yield


settings = get_settings()
app = FastAPI(
    title="Sentient Intelligence OS",
    version=PLATFORM_VERSION,
    description="Intelligence Operating System — Phase 0 foundation",
    lifespan=lifespan,
)

app.add_middleware( 
    CORSMiddleware, 
    allow_origins=["*"], # We'll restrict this after deployment 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"], )

app.include_router(router)
app.include_router(v2_router)
