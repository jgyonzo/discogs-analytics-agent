"""Integration test: full pipeline against curated tiny snapshot.

Stages releases_sample.xml + masters_sample.xml + artists_sample.xml in
a snapshot dir and asserts on the produced master_fact + the
backward-compatible release-side outputs.

Validates spec ``003-masters-artists`` US1 acceptance scenarios and
SC-001..SC-007.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import yaml
from click.testing import CliRunner

from discogs_etl.cli import cli


REPO_ROOT = Path(__file__).resolve().parents[3]
FIX = REPO_ROOT / "etl" / "tests" / "fixtures"


def _write_config(tmp_path: Path, *, snapshot_id: str = "discogs-test") -> Path:
    cfg = {
        "snapshot_id": snapshot_id,
        "paths": {
            "raw_dir": str(tmp_path / "data" / "raw" / "discogs"),
            "staging_dir": str(tmp_path / "data" / "staging"),
            "clean_dir": str(tmp_path / "data" / "clean"),
            "analytics_dir": str(tmp_path / "data" / "analytics"),
            "published_duckdb": str(tmp_path / "data" / "published" / "duckdb" / "discogs.duckdb"),
            "manifests_dir": str(tmp_path / "data" / "manifests"),
            "logs_dir": str(tmp_path / "data" / "logs"),
        },
        "limits": {
            "parser_batch_size": 1000,
            "log_progress_every": 100,
            "peak_rss_cap_gib": 4,
            "dq_check_in_memory_threshold": 10_000_000,
        },
    }
    config_path = tmp_path / "base.yml"
    config_path.write_text(yaml.safe_dump(cfg))
    raw_dir = Path(cfg["paths"]["raw_dir"]) / snapshot_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    return config_path


def _stage_all(tmp_path: Path, snapshot_id: str = "discogs-test") -> None:
    raw_dir = tmp_path / "data" / "raw" / "discogs" / snapshot_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIX / "releases_sample.xml", raw_dir / "releases.xml")
    shutil.copy2(FIX / "masters_sample.xml", raw_dir / "masters.xml")
    shutil.copy2(FIX / "artists_sample.xml", raw_dir / "artists.xml")


def test_curated_snapshot_publishes_master_fact_with_q3c_richness(tmp_path: Path):
    """SC-001..SC-005 + SC-006 + SC-007 against the curated tiny fixtures."""
    config_path = _write_config(tmp_path)
    _stage_all(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", str(config_path)])
    assert result.exit_code == 0, result.output

    manifests = list((tmp_path / "data" / "manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())

    # Clean artists row count = 5 (SC-006).
    ca_entry = manifest["outputs"]["clean"]["clean_artists"]
    assert ca_entry["row_count"] == 5

    # master_fact row count = 9 (5 from clean_masters + 4 orphan-from-releases).
    mf_entry = manifest["outputs"]["analytics"]["master_fact"]
    assert mf_entry["row_count"] == 9
    assert mf_entry["distinct_master_count"] == 9

    # Published tables include master_fact (FR-011 / SC-001).
    assert "master_fact" in manifest["outputs"]["published"]["duckdb"]["tables"]

    # Expected new warnings.
    warnings = [w["name"] for w in manifest["quality_checks"]["warnings"]]
    assert "build_master_fact.unknown_master_ids" in warnings
    assert "build_master_fact.main_release_unresolved" in warnings

    # Inspect master_fact data shape.
    db = tmp_path / "data" / "published" / "duckdb" / "discogs.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        # SC-001: row count.
        n = con.execute("SELECT COUNT(*) FROM master_fact").fetchone()[0]
        assert n == 9

        # SC-002 / FR-009: master 9001 → resolves to release 1001.
        r = con.execute(
            "SELECT title, primary_genre, primary_style, release_count, "
            "       earliest_year, latest_year "
            "FROM master_fact WHERE master_id = 9001"
        ).fetchone()
        assert r == ("Master Alpha", "Electronic", "Deep House", 1, 1999, 1999)

        # SC-004 (the key Q3=C two-LEFT-JOIN test): master 9003 → release 1003
        # which has NO styles. primary_genre populated, primary_style NULL.
        r = con.execute(
            "SELECT primary_genre, primary_style FROM master_fact WHERE master_id = 9003"
        ).fetchone()
        assert r == ("Rock", None)

        # Orphan-from-masters (no main_release, no releases): release_count=0,
        # all derived NULL.
        r = con.execute(
            "SELECT title, release_count, earliest_year, primary_genre, primary_style "
            "FROM master_fact WHERE master_id = 9999"
        ).fetchone()
        assert r[0].startswith("Master Lonely")
        assert r[1] == 0
        assert r[2] is None
        assert r[3] is None
        assert r[4] is None

        # Orphan-from-releases (master 9007 referenced by release 1007 but
        # not in clean_masters): NULL metadata, release_count=1.
        r = con.execute(
            "SELECT title, main_release_id, release_count "
            "FROM master_fact WHERE master_id = 9007"
        ).fetchone()
        assert r == (None, None, 1)

        # SC-003: cross-table consistency — SUM(release_count) =
        # COUNT(clean_releases WHERE master_id IS NOT NULL) = 7.
        sum_rc = con.execute("SELECT SUM(release_count) FROM master_fact").fetchone()[0]
        assert sum_rc == 7

        # Existing tables byte-stable (FR-018) — release_unique_view still works.
        n_view = con.execute("SELECT COUNT(*) FROM release_unique_view").fetchone()[0]
        assert n_view == 7
    finally:
        con.close()
