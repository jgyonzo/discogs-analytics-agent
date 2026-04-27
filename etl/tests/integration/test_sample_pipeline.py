"""Integration test: run the full pipeline against the curated fixture XML.

Covers the US1 happy path AND the FR-022/SC-006 failure path (bad fixture
must produce a quality_checks.status="failed" run AND leave the canonical
published DuckDB byte-identical).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import duckdb
import pytest
import yaml
from click.testing import CliRunner

from discogs_etl.cli import cli


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_GOOD = REPO_ROOT / "etl" / "tests" / "fixtures" / "releases_sample.xml"
FIXTURE_BAD = REPO_ROOT / "etl" / "tests" / "fixtures" / "releases_sample_bad.xml"


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
        "limits": {"parser_batch_size": 1000, "log_progress_every": 100},
    }
    config_path = tmp_path / "base.yml"
    config_path.write_text(yaml.safe_dump(cfg))
    raw_dir = Path(cfg["paths"]["raw_dir"]) / snapshot_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    return config_path


def _stage(fixture: Path, tmp_path: Path, snapshot_id: str) -> None:
    raw_dir = tmp_path / "data" / "raw" / "discogs" / snapshot_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture, raw_dir / "releases.xml")


def _read_manifest(tmp_path: Path, run_id: str) -> dict:
    return json.loads((tmp_path / "data" / "manifests" / f"{run_id}.json").read_text())


def _published(tmp_path: Path) -> Path:
    return tmp_path / "data" / "published" / "duckdb" / "discogs.duckdb"


def _sha256(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def test_happy_path_publishes_duckdb_with_v1_contract(tmp_path: Path):
    config_path = _write_config(tmp_path)
    _stage(FIXTURE_GOOD, tmp_path, "discogs-test")

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", str(config_path)])
    assert result.exit_code == 0, result.stderr

    # Find the run_id from the manifests dir.
    manifests = list((tmp_path / "data" / "manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["quality_checks"]["status"] in ("passed", "passed_with_warnings")
    assert "outputs" in manifest
    assert "published" in manifest["outputs"]
    assert "duckdb" in manifest["outputs"]["published"]

    # Inspect the published DuckDB.
    db = _published(tmp_path)
    assert db.exists()
    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'"
        ).fetchall()}
        assert tables >= {"release_fact", "release_artist_bridge", "release_label_bridge"}
        views = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW'"
        ).fetchall()}
        assert views == {"release_unique_view"}

        # 7 input releases, 9 release_fact rows (release 1007 has 3 styles → 3 rows;
        # releases 1003 and 1005 with 0 styles get 1 row each with style_order=0).
        n_distinct = con.execute(
            "SELECT COUNT(DISTINCT release_id) FROM release_fact"
        ).fetchone()[0]
        n_view = con.execute("SELECT COUNT(*) FROM release_unique_view").fetchone()[0]
        assert n_distinct == 7
        assert n_view == 7

        n_no_style = con.execute(
            "SELECT COUNT(*) FROM release_fact WHERE style_order = 0 AND style IS NULL"
        ).fetchone()[0]
        assert n_no_style == 2  # releases 1003 and 1005

        # Canonical agent query (US1 acceptance scenario 4).
        techno = con.execute(
            "SELECT decade, COUNT(DISTINCT release_id) AS releases "
            "FROM release_fact WHERE style='Techno' AND decade IS NOT NULL "
            "GROUP BY decade ORDER BY decade"
        ).fetchall()
        assert techno == [(2010, 1)]
    finally:
        con.close()


def test_failure_path_skips_publish_and_preserves_prior_db(tmp_path: Path):
    """FR-022 / SC-006: critical DQ failure must skip publish and leave the
    canonical published DuckDB byte-identical to its prior state."""
    config_path = _write_config(tmp_path)

    # Round 1: a passing run produces a published DB.
    _stage(FIXTURE_GOOD, tmp_path, "discogs-test")
    runner = CliRunner()
    r1 = runner.invoke(cli, ["run", "--config", str(config_path)])
    assert r1.exit_code == 0
    pre_hash = _sha256(_published(tmp_path))
    assert pre_hash is not None  # guaranteed by happy path

    # Round 2: feed the bad fixture (duplicate release_id).
    _stage(FIXTURE_BAD, tmp_path, "discogs-test")
    r2 = runner.invoke(cli, ["run", "--config", str(config_path)])
    assert r2.exit_code == 1, r2.stderr

    # The newest manifest reflects the failure; the prior good manifest is
    # untouched.
    manifest_paths = sorted((tmp_path / "data" / "manifests").glob("*.json"))
    assert len(manifest_paths) == 2
    failed = json.loads(manifest_paths[-1].read_text())
    assert failed["quality_checks"]["status"] == "failed"
    assert "duckdb" not in failed["outputs"].get("published", {})

    # Canonical published DB byte-identical.
    post_hash = _sha256(_published(tmp_path))
    assert post_hash == pre_hash, "Published DuckDB must be byte-identical on failed run (FR-022)"
