"""GET /health helpers — multi-component liveness check.

Spec: `specs/004-agent-v1/contracts/api.md` §5 and `research.md` R-10.

Two independent probes:
- ``check_duckdb`` — file present, opens read-only, four core tables
  reachable. ``has_master_fact`` is reported separately and is **not**
  required for ``ok`` (FR-011). Uses a writable ``temp_directory`` so
  the read-only mount can't trip DuckDB's adjacent ``<dbfile>.tmp/``
  spill (Constitution VII.c / research R-14).
- ``check_postgres`` — SELECT 1 enforced by a 1-second wall-clock
  timeout. The timeout is implemented via ``concurrent.futures`` so it
  works the same way against psycopg and SQLite (the test backend).

``build_health_payload`` aggregates both into the contracted shape and
returns the matching HTTP status (200 ok / 503 unavailable).
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import Engine, text

from discogs_agent.config import settings
from discogs_agent.duckdb_layer.allowlist import ALLOWED_TABLES
from discogs_agent.observability import logging as obslog

logger = obslog.get_logger(__name__)

_CORE_TABLES_REQUIRED: tuple[str, ...] = (
    "release_fact",
    "release_unique_view",
    "release_artist_bridge",
    "release_label_bridge",
)

POSTGRES_TIMEOUT_SECONDS: float = 1.0


def check_duckdb(duckdb_path: str | Path) -> dict[str, Any]:
    path = Path(duckdb_path)
    out: dict[str, Any] = {
        "ok": False,
        "path": str(path),
        "tables_present": [],
        "has_master_fact": False,
        "error": None,
    }
    if not path.exists():
        out["error"] = f"file not found: {path}"
        return out
    try:
        con = duckdb.connect(
            str(path),
            read_only=True,
            config={"temp_directory": "/tmp/duckdb"},
        )
    except duckdb.Error as exc:
        out["error"] = f"open_failed: {type(exc).__name__}: {exc}"
        return out
    try:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    except duckdb.Error as exc:
        out["error"] = f"query_failed: {type(exc).__name__}: {exc}"
        return out
    finally:
        con.close()

    present = {r[0] for r in rows}
    out["tables_present"] = [t for t in ALLOWED_TABLES if t in present]

    missing_core = [t for t in _CORE_TABLES_REQUIRED if t not in present]
    if missing_core:
        out["error"] = f"missing_core_tables: {missing_core}"
        return out

    out["has_master_fact"] = "master_fact" in present
    out["ok"] = True
    return out


def check_postgres(engine: Engine, timeout: float = POSTGRES_TIMEOUT_SECONDS) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": None}

    def _probe() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_probe)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            out["error"] = f"timeout_after_{timeout}s"
            return out
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    out["ok"] = True
    return out


def build_health_payload() -> tuple[dict[str, Any], int]:
    """Compose both checks into the contract-defined response shape and
    return ``(payload, http_status_code)``."""
    duckdb_check = check_duckdb(settings.ANALYTICS_DUCKDB_PATH)

    try:
        from discogs_agent.persistence.db import get_engine

        pg_check = check_postgres(get_engine())
    except Exception as exc:
        pg_check = {
            "ok": False,
            "error": f"engine_unavailable: {type(exc).__name__}: {exc}",
        }

    overall_ok = bool(duckdb_check["ok"]) and bool(pg_check["ok"])
    payload: dict[str, Any] = {
        "status": "ok" if overall_ok else "unavailable",
        "checks": {"duckdb": duckdb_check, "postgres": pg_check},
        "version": settings.AGENT_VERSION,
        "model_provider": "openai",
    }
    return payload, 200 if overall_ok else 503
