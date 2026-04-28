"""Integration test: release-only snapshot (Fase 4 backward-compat).

Stages ONLY ``releases.xml`` in the snapshot dir (no masters / no
artists XML). Asserts that the pipeline produces a Fase 1+2+3-shaped
DuckDB (no master_fact table) plus the two new
``prepare_sources.{masters,artists}_missing`` warnings.

Validates spec ``003-masters-artists`` SC-020 / SC-021.
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


def test_release_only_snapshot_publishes_no_master_fact(tmp_path: Path):
    config_path = _write_config(tmp_path)
    raw_dir = tmp_path / "data" / "raw" / "discogs" / "discogs-test"
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIX / "releases_sample.xml", raw_dir / "releases.xml")
    # No masters.xml, no artists.xml.

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", str(config_path)])
    assert result.exit_code == 0, result.output

    manifest = json.loads(
        next((tmp_path / "data" / "manifests").glob("*.json")).read_text()
    )

    # Two new missing-input warnings.
    warning_names = [w["name"] for w in manifest["quality_checks"]["warnings"]]
    assert "prepare_sources.masters_missing" in warning_names
    assert "prepare_sources.artists_missing" in warning_names

    # No master_fact in outputs.analytics.
    assert "master_fact" not in manifest["outputs"]["analytics"]

    # Published DuckDB tables list does NOT include master_fact.
    published = manifest["outputs"]["published"]["duckdb"]["tables"]
    assert published == [
        "release_fact", "release_artist_bridge", "release_label_bridge",
    ]

    # Inspect DuckDB to confirm master_fact table truly isn't there.
    db = tmp_path / "data" / "published" / "duckdb" / "discogs.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE'"
        ).fetchall()}
        assert "master_fact" not in tables
        assert tables == {
            "release_fact", "release_artist_bridge", "release_label_bridge",
        }
    finally:
        con.close()
