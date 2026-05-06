"""Reproducibility check on the seed DuckDB binaries.

Builds fresh seeds in a tmp dir from `seed_duckdb.py` and asserts the
structural shape (table list + row counts) matches the committed
binaries. Byte-equality is not asserted — DuckDB internals change.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _import_seed_builder() -> object:
    spec = importlib.util.spec_from_file_location(
        "_agent_tests_seed_duckdb",
        FIXTURES_DIR / "seed_duckdb.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_seed_duckdb = _import_seed_builder().build_seed_duckdb  # type: ignore[attr-defined]


def _shape(path: Path) -> dict[str, int]:
    """Returns {table_name: row_count} for all tables/views."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        out: dict[str, int] = {}
        for (name,) in rows:
            count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            out[name] = int(count)
        return out
    finally:
        con.close()


@pytest.mark.parametrize(
    "filename,with_master",
    [
        ("seed.duckdb", True),
        ("seed_no_master.duckdb", False),
    ],
)
def test_seed_duckdb_round_trip(tmp_path: Path, filename: str, with_master: bool) -> None:
    committed = FIXTURES_DIR / filename
    assert committed.exists(), (
        f"Missing committed fixture {committed}. Rebuild it with "
        f"`python -m agent.tests.fixtures.seed_duckdb`."
    )

    fresh = tmp_path / filename
    build_seed_duckdb(fresh, with_master_fact=with_master)

    assert _shape(committed) == _shape(fresh), (
        "Seed DuckDB structure drifted from the seed_duckdb.py builder. "
        "Rebuild with `python -m agent.tests.fixtures.seed_duckdb` and "
        "commit the updated binaries."
    )
