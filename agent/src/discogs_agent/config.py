"""Agent configuration via pydantic-settings.

Single source of truth for env-driven knobs. Loaded once at import.
`validate_runtime()` is called from FastAPI startup to fail fast
on misconfiguration before serving any request.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Env-driven runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # DuckDB (the only data path between components).
    ANALYTICS_DUCKDB_PATH: str = "/app/data/published/duckdb/discogs.duckdb"

    # Persistence (Postgres in prod, SQLite-in-memory in tests).
    DATABASE_URL: str = "postgresql+psycopg://agent:agent@postgres:5432/agent"

    # Artifact directory.
    ARTIFACTS_DIR: str = "/app/artifacts"

    # LLM provider — V1 = OpenAI.
    OPENAI_API_KEY: str = ""
    CHEAP_MODEL: str = "gpt-4o-mini"
    STRONG_MODEL: str = "gpt-4o"

    # Retry budget across safety + validation paths.
    MAX_RETRIES: int = 2

    # Sandbox hard wall-clock cap.
    SANDBOX_TIMEOUT_SECONDS: int = 30

    # Multi-turn carry-over (US4).
    THREAD_CARRYOVER_TURNS: int = 4
    THREAD_CARRYOVER_TOKEN_BUDGET: int = 512

    # LLM backend selector. "openai" = real, "stub" = in-process for tests.
    LLM_BACKEND: str = "openai"

    # Logging.
    LOG_LEVEL: str = "INFO"

    # Admin auth (US3). Empty disables admin mode entirely.
    AGENT_ADMIN_TOKEN: str = ""

    # Build version for /health (set by Docker build args).
    AGENT_VERSION: str = Field(default="dev")

    def validate_runtime(self) -> None:
        """Fail fast on misconfiguration. Called from FastAPI startup."""
        if self.LLM_BACKEND == "openai" and not self.OPENAI_API_KEY:
            raise RuntimeError(
                "LLM_BACKEND=openai but OPENAI_API_KEY is empty. "
                "Set it in .env or switch to LLM_BACKEND=stub for tests."
            )
        if not Path(self.ANALYTICS_DUCKDB_PATH).exists():
            raise RuntimeError(
                f"ANALYTICS_DUCKDB_PATH does not exist: {self.ANALYTICS_DUCKDB_PATH}. "
                "Produce a published DuckDB via the ETL first."
            )
        Path(self.ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)


settings = AgentSettings()
