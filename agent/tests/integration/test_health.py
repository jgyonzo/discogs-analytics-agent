"""US2 / T080 — /health integration test.

Spins up a real Postgres via testcontainers, points the agent at the
seed DuckDB, and hits ``GET /health`` over the FastAPI TestClient.
Skips when Docker / testcontainers is unavailable so the rest of the
suite still runs on a developer laptop without Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_health_against_postgres_and_seed_duckdb(
    seed_duckdb: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    from discogs_agent.api import app
    from discogs_agent.config import settings
    from discogs_agent.duckdb_layer import schema as schema_module
    from discogs_agent.persistence.db import init_engine, reset_engine
    from discogs_agent.persistence.models import Base

    try:
        pg = PostgresContainer("postgres:16-alpine")
        pg.start()
    except Exception as exc:  # docker unreachable
        pytest.skip(f"docker/testcontainers unavailable: {exc}")

    try:
        url = pg.get_connection_url().replace("psycopg2", "psycopg")
        monkeypatch.setattr(settings, "DATABASE_URL", url)
        monkeypatch.setattr(
            settings, "ANALYTICS_DUCKDB_PATH", str(seed_duckdb)
        )
        schema_module.reset_schema_cache()
        reset_engine()
        engine = init_engine(url)
        Base.metadata.create_all(engine)

        with TestClient(app) as client:
            resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["model_provider"] == "openai"
        assert body["version"]
        duckdb_check = body["checks"]["duckdb"]
        assert duckdb_check["ok"] is True
        assert duckdb_check["has_master_fact"] is True
        assert duckdb_check["error"] is None
        assert "release_fact" in duckdb_check["tables_present"]
        assert body["checks"]["postgres"]["ok"] is True
        assert body["checks"]["postgres"]["error"] is None
    finally:
        reset_engine()
        pg.stop()
