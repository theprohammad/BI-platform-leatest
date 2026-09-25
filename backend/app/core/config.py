"""Central configuration. Rule: nothing tunable is hard-coded anywhere else.

Every model name, timeout, budget and provider choice lives here so that
provider independence (Blueprint rule 6) and cost control are config, not code.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- environment -------------------------------------------------------
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # --- providers (Blueprint rule 6: replaceable behind interfaces) -------
    llm_provider: str = "nvidia"
    search_provider: str = "tavily"
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    groq_api_key: str = ""  # legacy compatibility; prefer NVIDIA settings
    tavily_api_key: str = ""

    # --- LLM routing tiers (Blueprint Part VIII) ----------------------------
    model_extract: str = "meta/llama-3.2-11b-vision-instruct"
    model_reason: str = "meta/llama-3.2-11b-vision-instruct"
    model_judge: str = "meta/llama-3.2-11b-vision-instruct"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1  # one JSON-repair retry
    llm_temperature: float = 0.2
    # --- performance layer (Priority Zero) ----------------------------------
    llm_max_concurrent: int = 4       # cap concurrent upstream LLM calls (429 guard)
    llm_cache_ttl_seconds: float = 1800.0
    search_cache_ttl_seconds: float = 3600.0

    # --- search / evidence ---------------------------------------------------
    search_depth: Literal["basic", "advanced"] = "advanced"
    search_max_results: int = 5
    # None = keep full content (rule 4: stop discarding paid evidence).
    search_content_max_chars: int | None = None
    website_fetch_timeout: float = 15.0

    # --- budgets (research must terminate) ----------------------------------
    run_token_budget: int = 250_000
    run_wallclock_budget_seconds: float = 600.0

    # --- persistence (optional in Phase 0; required from Phase 1) -----------
    database_url: str = ""  # e.g. postgresql+asyncpg://user:pass@host/db

    # --- Phase 2 subsystem flags (rollback strategy §6 of the tech spec) ----
    retrieval_strategy: Literal["keyword", "hybrid"] = "hybrid"
    planner_mode: Literal["v1", "v2"] = "v2"
    resolution_auto_merge: bool = False   # asymmetric policy: OFF in prod
    embedding_provider: Literal["hashing", "fastembed"] = "hashing"
    embedding_dim: int = 384
    # refresh targeting thresholds (S8)
    refresh_staleness_days: float = 30.0
    refresh_min_confidence: float = 0.45
    refresh_url_fanin_min: int = 2
    refresh_url_cap: int = 5

    # --- API ----------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
