"""Read the published DuckDB's allowlisted shape into an in-memory
`SchemaContext`. Module-level cache; built once at startup, reused by
every request. Refreshed only on process restart.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import duckdb

from discogs_agent.duckdb_layer.allowlist import (
    ALLOWED_TABLES,
    is_explicitly_forbidden,
)


class SchemaContext(TypedDict):
    tables: dict[str, list[dict[str, str]]]
    has_master_fact: bool
    duckdb_path: str
    captured_at: str
    warnings: list[str]


_CORE_TABLES_REQUIRED = (
    "release_fact",
    "release_unique_view",
    "release_artist_bridge",
    "release_label_bridge",
)


_cache: SchemaContext | None = None


def read_schema_context(duckdb_path: str | Path) -> SchemaContext:
    """Open DuckDB read-only and snapshot the allowlisted catalog.

    Raises FileNotFoundError if the file is absent.
    Raises RuntimeError if any of the four core tables is absent.
    `master_fact` is optional and reflected in `has_master_fact`.
    """
    path = Path(duckdb_path)
    if not path.exists():
        raise FileNotFoundError(f"DuckDB not found at {path}")

    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        present = {r[0] for r in rows}

        warnings: list[str] = []
        for name in present:
            if is_explicitly_forbidden(name):
                warnings.append(
                    f"Found non-allowlisted table {name!r} in published DuckDB; filtered out"
                )

        missing_core = [t for t in _CORE_TABLES_REQUIRED if t not in present]
        if missing_core:
            raise RuntimeError(
                f"Published DuckDB is missing required core tables: {missing_core}. "
                "Re-run the ETL on this snapshot."
            )

        tables: dict[str, list[dict[str, str]]] = {}
        for table in ALLOWED_TABLES:
            if table not in present:
                continue
            col_rows = con.execute(
                f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = '{table}'
                ORDER BY ordinal_position
                """
            ).fetchall()
            tables[table] = [{"name": c[0], "type": c[1]} for c in col_rows]

        has_master = "master_fact" in tables

        return SchemaContext(
            tables=tables,
            has_master_fact=has_master,
            duckdb_path=str(path),
            captured_at=datetime.now(timezone.utc).isoformat(),
            warnings=warnings,
        )
    finally:
        con.close()


def get_schema_context(duckdb_path: str | Path) -> SchemaContext:
    """Cached accessor. Returns the same context across calls in one process."""
    global _cache
    if _cache is None:
        _cache = read_schema_context(duckdb_path)
    return _cache


def reset_schema_cache() -> None:
    """Test helper."""
    global _cache
    _cache = None
