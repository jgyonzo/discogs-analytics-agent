"""Tests for the dataset_schema_reader tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from discogs_agent.duckdb_layer import schema as schema_module
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.dataset_schema_reader import (
    SchemaReaderInput,
    dataset_schema_reader,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    schema_module.reset_schema_cache()


def test_reads_seed_with_master(seed_duckdb: Path) -> None:
    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=str(seed_duckdb)))
    assert out.has_master_fact is True
    assert "release_fact" in out.tables
    assert "release_unique_view" in out.tables
    assert "release_artist_bridge" in out.tables
    assert "release_label_bridge" in out.tables
    assert "master_fact" in out.tables


def test_reads_seed_without_master(seed_duckdb_no_master: Path) -> None:
    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=str(seed_duckdb_no_master)))
    assert out.has_master_fact is False
    assert "master_fact" not in out.tables
    # Core tables still present.
    for required in (
        "release_fact",
        "release_unique_view",
        "release_artist_bridge",
        "release_label_bridge",
    ):
        assert required in out.tables


def test_filters_non_allowlisted_tables(seed_duckdb: Path, tmp_path: Path) -> None:
    """If we splice a stg_* table into a copy of the seed DuckDB, the
    schema reader filters it out and warns."""
    import shutil

    import duckdb

    seed_copy = tmp_path / "seed_with_stg.duckdb"
    shutil.copy(seed_duckdb, seed_copy)

    con = duckdb.connect(str(seed_copy))
    try:
        con.execute("CREATE TABLE stg_releases (release_id BIGINT)")
    finally:
        con.close()

    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=str(seed_copy)))

    assert "stg_releases" not in out.tables
    assert any("stg_releases" in w for w in out.warnings)
