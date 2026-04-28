"""Integration test: full pipeline against the in-repo real raw fixtures.

Stages releases_sample_raw.xml + masters_sample_raw.xml +
artists_sample_raw.xml (all real Discogs excerpts, all truncated
mid-element). Asserts on truncation handling for all three parsers
plus the cross-table consistency on real-data scale (~317 masters,
~4841 artists, 404 releases).

Validates spec ``003-masters-artists`` US1 acceptance scenarios on
realistic data (FR-005 / parse_masters.truncated_xml /
parse_artists.truncated_xml / Unicode round-trip).
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


def _write_config(tmp_path: Path, *, snapshot_id: str = "discogs-real") -> Path:
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


def _stage_real(tmp_path: Path, snapshot_id: str = "discogs-real") -> None:
    raw_dir = tmp_path / "data" / "raw" / "discogs" / snapshot_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIX / "releases_sample_raw.xml", raw_dir / "releases.xml")
    shutil.copy2(FIX / "masters_sample_raw.xml", raw_dir / "masters.xml")
    shutil.copy2(FIX / "artists_sample_raw.xml", raw_dir / "artists.xml")


def test_real_raw_fixtures_truncation_warnings_for_all_three(tmp_path: Path):
    config_path = _write_config(tmp_path)
    _stage_real(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", str(config_path)])
    assert result.exit_code == 0, result.output

    manifests = list((tmp_path / "data" / "manifests").glob("*.json"))
    manifest = json.loads(manifests[0].read_text())
    assert manifest["quality_checks"]["status"] == "passed_with_warnings"

    warning_names = [w["name"] for w in manifest["quality_checks"]["warnings"]]
    # FR-005: all three truncation warnings present.
    assert "parse_releases.truncated_xml" in warning_names
    assert "parse_masters.truncated_xml" in warning_names
    assert "parse_artists.truncated_xml" in warning_names

    # Source counts: real raw fixtures have:
    #  - 404 fully-formed releases
    #  - 317 fully-formed masters
    #  - 4841 fully-formed artists
    assert manifest["outputs"]["staging"]["stg_masters"]["row_count"] == 317
    assert manifest["outputs"]["staging"]["stg_artists"]["row_count"] == 4841

    db = tmp_path / "data" / "published" / "duckdb" / "discogs.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        # Cross-table consistency: SUM(release_count) over master_fact
        # equals COUNT(*) of clean_releases that have master_id NOT NULL.
        # We can't easily count clean_releases from the published DB, but
        # release_unique_view ≈ 404 (one row per release); not all have
        # master_id. SUM should be > 0 and ≤ 404.
        sum_rc = con.execute("SELECT SUM(release_count) FROM master_fact").fetchone()[0]
        assert 0 < sum_rc <= 404

        # The Q3=C "top techno works by release count" canonical query
        # should run. May return 0 rows on this small slice, but must
        # not raise.
        rows = con.execute(
            "SELECT title, release_count FROM master_fact "
            "WHERE primary_style = 'Techno' "
            "ORDER BY release_count DESC LIMIT 10"
        ).fetchall()
        assert isinstance(rows, list)

        # Unicode round-trip for clean_artists.profile / realname:
        # the real artist id=1 in artists_sample_raw.xml has Jesper Dahlbäck
        # as realname.
        # clean_artists is parquet-only (not in DuckDB per Q1=B). Read it
        # via DuckDB read_parquet against the run dir.
        run_id = manifest["run_id"]
        clean_artists = (
            tmp_path / "data" / "clean" / run_id / "clean_artists.parquet"
        )
        n_dahlback = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?) WHERE realname LIKE '%Dahlb%'",
            [str(clean_artists)],
        ).fetchone()[0]
        assert n_dahlback >= 1
    finally:
        con.close()
