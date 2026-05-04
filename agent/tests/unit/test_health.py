"""US2 / T079 — unit tests for the /health probes.

Exercises every branch of `discogs_agent.health.check_duckdb` and
`check_postgres` plus the aggregate `build_health_payload`. Postgres
is faked via small in-memory SQLite engines (real engine for the
ok-path, mocked Engine.connect raising for the failure paths) so the
tests never need a network or testcontainers.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import pytest
from sqlalchemy import create_engine

from discogs_agent import health


def _build_minimal_duckdb(path: Path, *, tables: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        for t in tables:
            con.execute(f"CREATE TABLE {t} (x INTEGER)")
    finally:
        con.close()


# ─── DuckDB probe ─────────────────────────────────────────────────────


def test_duckdb_missing_file(tmp_path: Path) -> None:
    out = health.check_duckdb(tmp_path / "does-not-exist.duckdb")
    assert out["ok"] is False
    assert out["error"] is not None
    assert "file not found" in out["error"]
    assert out["tables_present"] == []
    assert out["has_master_fact"] is False


def test_duckdb_missing_core_table(tmp_path: Path) -> None:
    db = tmp_path / "partial.duckdb"
    _build_minimal_duckdb(
        db,
        tables=[
            "release_fact",
            "release_unique_view",
            "release_artist_bridge",
            # release_label_bridge intentionally omitted
        ],
    )
    out = health.check_duckdb(db)
    assert out["ok"] is False
    assert out["error"] is not None
    assert "release_label_bridge" in out["error"]


def test_duckdb_with_master_fact(seed_duckdb: Path) -> None:
    out = health.check_duckdb(seed_duckdb)
    assert out["ok"] is True
    assert out["error"] is None
    assert out["has_master_fact"] is True
    assert "master_fact" in out["tables_present"]
    for core in (
        "release_fact",
        "release_unique_view",
        "release_artist_bridge",
        "release_label_bridge",
    ):
        assert core in out["tables_present"]


def test_duckdb_without_master_fact_is_ok(seed_duckdb_no_master: Path) -> None:
    out = health.check_duckdb(seed_duckdb_no_master)
    assert out["ok"] is True
    assert out["has_master_fact"] is False
    assert "master_fact" not in out["tables_present"]


# ─── Postgres probe ───────────────────────────────────────────────────


def test_postgres_ok_against_sqlite() -> None:
    """SQLite stands in for Postgres for unit tests; the SELECT 1
    contract is identical."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    try:
        out = health.check_postgres(engine)
        assert out["ok"] is True
        assert out["error"] is None
    finally:
        engine.dispose()


def test_postgres_failure_when_engine_disposed() -> None:
    """Dispose the engine and force a connection — the underlying
    pool error surfaces in `error`."""
    engine = create_engine(
        "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none",
        future=True,
        connect_args={"connect_timeout": 1},
    )
    out = health.check_postgres(engine, timeout=3.0)
    assert out["ok"] is False
    assert out["error"] is not None


def test_postgres_timeout_kicks_in() -> None:
    """Patch the inner _probe to sleep longer than the timeout — the
    health check must return ok=False with a timeout-shaped error."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    real_probe = engine.connect

    def _slow_connect(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.5)
        return real_probe(*args, **kwargs)

    with patch.object(engine, "connect", side_effect=_slow_connect):
        out = health.check_postgres(engine, timeout=0.05)
    assert out["ok"] is False
    assert out["error"] is not None
    assert "timeout" in out["error"]
    engine.dispose()


# ─── Aggregate payload ────────────────────────────────────────────────


def test_build_payload_both_up(
    seed_duckdb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discogs_agent.config import settings
    from discogs_agent.persistence.db import init_engine, reset_engine

    monkeypatch.setattr(settings, "ANALYTICS_DUCKDB_PATH", str(seed_duckdb))
    reset_engine()
    init_engine("sqlite+pysqlite:///:memory:")
    try:
        payload, status_code = health.build_health_payload()
    finally:
        reset_engine()

    assert status_code == 200
    assert payload["status"] == "ok"
    assert payload["model_provider"] == "openai"
    assert payload["version"]  # non-empty
    assert payload["checks"]["duckdb"]["ok"] is True
    assert payload["checks"]["duckdb"]["has_master_fact"] is True
    assert payload["checks"]["postgres"]["ok"] is True


def test_build_payload_duckdb_down_is_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discogs_agent.config import settings
    from discogs_agent.persistence.db import init_engine, reset_engine

    monkeypatch.setattr(
        settings, "ANALYTICS_DUCKDB_PATH", str(tmp_path / "nope.duckdb")
    )
    reset_engine()
    init_engine("sqlite+pysqlite:///:memory:")
    try:
        payload, status_code = health.build_health_payload()
    finally:
        reset_engine()

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"]["duckdb"]["ok"] is False
    assert payload["checks"]["postgres"]["ok"] is True


def test_build_payload_postgres_down_is_503(
    seed_duckdb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discogs_agent.config import settings
    from discogs_agent.persistence.db import reset_engine

    monkeypatch.setattr(settings, "ANALYTICS_DUCKDB_PATH", str(seed_duckdb))
    reset_engine()

    def _boom() -> None:
        raise RuntimeError("forced engine failure")

    with patch(
        "discogs_agent.persistence.db.get_engine",
        side_effect=_boom,
    ):
        payload, status_code = health.build_health_payload()

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"]["duckdb"]["ok"] is True
    assert payload["checks"]["postgres"]["ok"] is False
    assert "engine_unavailable" in payload["checks"]["postgres"]["error"]


def test_build_payload_both_down_is_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discogs_agent.config import settings
    from discogs_agent.persistence.db import reset_engine

    monkeypatch.setattr(
        settings, "ANALYTICS_DUCKDB_PATH", str(tmp_path / "missing.duckdb")
    )
    reset_engine()

    def _boom() -> None:
        raise RuntimeError("nope")

    with patch(
        "discogs_agent.persistence.db.get_engine",
        side_effect=_boom,
    ):
        payload, status_code = health.build_health_payload()

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"]["duckdb"]["ok"] is False
    assert payload["checks"]["postgres"]["ok"] is False
