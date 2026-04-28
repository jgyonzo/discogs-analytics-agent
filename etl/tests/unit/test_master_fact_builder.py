"""Unit test for BuildMasterFactStep against synthetic clean inputs.

Validates the two-LEFT-JOIN derivation of primary_genre / primary_style
(per spec ``003-masters-artists`` task T020 fix) and the
master_universe ∪ semantics (orphan masters from both sides).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from discogs_etl.io import schemas
from discogs_etl.io.parquet_writer import BatchedParquetWriter
from discogs_etl.pipeline.context import LimitConfig, PathConfig, RunConfig, RunContext
from discogs_etl.pipeline.manifest import Manifest
from discogs_etl.steps.build_master_fact import BuildMasterFactStep


def _write(path: Path, schema: pa.Schema, rows: list[dict]) -> None:
    with BatchedParquetWriter(path, schema, batch_size=1000) as w:
        for r in rows:
            w.write(r)


def _make_ctx(tmp_path: Path) -> tuple[RunContext, Manifest]:
    cfg = RunConfig(
        snapshot_id="testsnap",
        paths=PathConfig(
            raw_dir=tmp_path / "raw",
            staging_dir=tmp_path / "staging",
            clean_dir=tmp_path / "clean",
            analytics_dir=tmp_path / "analytics",
            published_duckdb=tmp_path / "published" / "discogs.duckdb",
            manifests_dir=tmp_path / "manifests",
            logs_dir=tmp_path / "logs",
        ),
        limits=LimitConfig(parser_batch_size=1000, log_progress_every=1000),
        config_path=tmp_path / "fake-config.yml",
        config_sha256="0" * 64,
    )
    rid = "testrun-mfb"
    logger = logging.getLogger("discogs_etl.tests.mfb")
    ctx = RunContext(run_id=rid, snapshot_id=cfg.snapshot_id, config=cfg, logger=logger)
    for d in (ctx.clean_dir, ctx.analytics_dir, cfg.paths.manifests_dir):
        d.mkdir(parents=True, exist_ok=True)
    manifest = Manifest.create(
        ctx.manifest_path,
        run_id=rid, snapshot_id=cfg.snapshot_id,
        etl_version="0.0.0-test",
        started_at="2026-04-27T00:00:00Z",
        config_path=cfg.config_path, config_sha256=cfg.config_sha256,
    )
    return ctx, manifest


def test_master_fact_two_left_join_handles_no_styles(tmp_path: Path):
    """Master 200 references release 20 which has no styles.
    primary_genre must be populated; primary_style must be NULL."""
    ctx, manifest = _make_ctx(tmp_path)
    rid = ctx.run_id

    # clean_releases:
    #  release 10 → master 100 (year 1999)
    #  release 20 → master 200 (year 1985, NO STYLES)
    #  release 30 → master 100 (year 2010, gives master 100 release_count=2)
    #  release 40 → master 999 (orphan-from-releases — master 999 is NOT in clean_masters)
    _write(ctx.clean_dir / "clean_releases.parquet", schemas.CLEAN_RELEASES, [
        {"release_id": 10, "title": "R10", "country": "UK", "released_raw": "1999",
         "year": 1999, "month": None, "day": None, "released_date": None,
         "released_date_precision": "year", "decade": 1990, "data_quality": "Correct",
         "master_id": 100, "master_is_main_release": True,
         "track_count": 0, "artist_count": 1, "label_count": 1,
         "genre_count": 1, "style_count": 1, "format_count": 1,
         "has_videos": False, "has_extraartists": False, "run_id": rid},
        {"release_id": 20, "title": "R20", "country": "UK", "released_raw": "1985",
         "year": 1985, "month": None, "day": None, "released_date": None,
         "released_date_precision": "year", "decade": 1980, "data_quality": "Correct",
         "master_id": 200, "master_is_main_release": True,
         "track_count": 0, "artist_count": 1, "label_count": 1,
         "genre_count": 1, "style_count": 0, "format_count": 1,
         "has_videos": False, "has_extraartists": False, "run_id": rid},
        {"release_id": 30, "title": "R30", "country": "UK", "released_raw": "2010",
         "year": 2010, "month": None, "day": None, "released_date": None,
         "released_date_precision": "year", "decade": 2010, "data_quality": "Correct",
         "master_id": 100, "master_is_main_release": False,
         "track_count": 0, "artist_count": 1, "label_count": 1,
         "genre_count": 1, "style_count": 1, "format_count": 1,
         "has_videos": False, "has_extraartists": False, "run_id": rid},
        {"release_id": 40, "title": "R40", "country": "UK", "released_raw": "2020",
         "year": 2020, "month": None, "day": None, "released_date": None,
         "released_date_precision": "year", "decade": 2020, "data_quality": "Correct",
         "master_id": 999, "master_is_main_release": False,
         "track_count": 0, "artist_count": 1, "label_count": 1,
         "genre_count": 1, "style_count": 1, "format_count": 1,
         "has_videos": False, "has_extraartists": False, "run_id": rid},
    ])

    # clean_masters: 100 (resolves), 200 (resolves but release has no styles),
    # 300 (orphan-from-masters: no release references it).
    _write(ctx.clean_dir / "clean_masters.parquet", schemas.CLEAN_MASTERS, [
        {"master_id": 100, "title": "Master 100", "main_release_id": 10,
         "year": 1999, "decade": 1990, "year_precision": "year", "run_id": rid},
        {"master_id": 200, "title": "Master 200 no-styles release",
         "main_release_id": 20, "year": 1985, "decade": 1980,
         "year_precision": "year", "run_id": rid},
        {"master_id": 300, "title": "Master 300 orphan", "main_release_id": None,
         "year": 1990, "decade": 1990, "year_precision": "year", "run_id": rid},
    ])

    # release_fact: row-multiplied by style.
    # release 10: 1 row at style_order=1 (primary_genre=Electronic, style=Techno)
    # release 20: 1 row at style_order=0 (NO styles; primary_genre=Rock, style=NULL)
    # release 30: 1 row at style_order=1 (primary_genre=Electronic, style=House)
    # release 40: 1 row at style_order=1 (primary_genre=Pop, style=Synth)
    common = {
        "country": "UK", "released_raw": None, "year": None, "month": None,
        "day": None, "released_date": None, "released_date_precision": "year",
        "decade": None, "data_quality": "Correct", "track_count": 0,
        "artist_count": 1, "label_count": 1, "genre_count": 1, "style_count": 1,
        "format_count": 1, "primary_label_id": None, "primary_label_name": None,
        "primary_format_raw": None, "primary_format_group": "Vinyl",
        "format_quantity": None, "format_description_summary": None,
        "has_vinyl": True, "has_cd": False, "has_cassette": False,
        "has_digital": False, "has_box_set": False,
        "primary_artist_id": None, "primary_artist_name": None,
        "title": None, "master_id": None, "run_id": rid,
    }
    _write(ctx.analytics_dir / "release_fact.parquet", schemas.RELEASE_FACT, [
        {**common, "release_id": 10, "primary_genre": "Electronic",
         "style": "Techno", "style_order": 1},
        {**common, "release_id": 20, "primary_genre": "Rock",
         "style": None, "style_order": 0},
        {**common, "release_id": 30, "primary_genre": "Electronic",
         "style": "House", "style_order": 1},
        {**common, "release_id": 40, "primary_genre": "Pop",
         "style": "Synth", "style_order": 1},
    ])

    BuildMasterFactStep().run(ctx, manifest)

    mf = pq.read_table(ctx.analytics_dir / "master_fact.parquet")
    rows = {r["master_id"]: r for r in mf.to_pylist()}

    # 4 distinct master_ids: 100, 200, 300 (from clean_masters) + 999 (orphan-from-releases).
    assert set(rows.keys()) == {100, 200, 300, 999}
    assert mf.num_rows == 4

    # Master 100: 2 releases, earliest 1999, latest 2010, main_release=10.
    r100 = rows[100]
    assert r100["release_count"] == 2
    assert r100["earliest_year"] == 1999
    assert r100["latest_year"] == 2010
    assert r100["primary_genre"] == "Electronic"
    assert r100["primary_style"] == "Techno"  # from release 10 at style_order=1.

    # Master 200: release 20 has no styles. primary_genre populated; primary_style NULL.
    r200 = rows[200]
    assert r200["release_count"] == 1
    assert r200["primary_genre"] == "Rock"
    assert r200["primary_style"] is None  # ← key assertion: two-LEFT-JOIN handles style_order=0

    # Master 300: orphan-from-masters (no releases reference it).
    r300 = rows[300]
    assert r300["release_count"] == 0
    assert r300["earliest_year"] is None
    assert r300["latest_year"] is None
    assert r300["primary_genre"] is None
    assert r300["primary_style"] is None

    # Master 999: orphan-from-releases (no entry in clean_masters).
    r999 = rows[999]
    assert r999["title"] is None
    assert r999["main_release_id"] is None
    assert r999["release_count"] == 1
    assert r999["earliest_year"] == 2020
    assert r999["primary_genre"] is None
    assert r999["primary_style"] is None


def test_master_fact_distinct_master_count_recorded(tmp_path: Path):
    """The manifest output entry must include distinct_master_count."""
    ctx, manifest = _make_ctx(tmp_path)
    rid = ctx.run_id

    _write(ctx.clean_dir / "clean_releases.parquet", schemas.CLEAN_RELEASES, [
        {"release_id": 1, "title": "R1", "country": "UK", "released_raw": "2000",
         "year": 2000, "month": None, "day": None, "released_date": None,
         "released_date_precision": "year", "decade": 2000, "data_quality": "Correct",
         "master_id": 1, "master_is_main_release": True,
         "track_count": 0, "artist_count": 1, "label_count": 1, "genre_count": 1,
         "style_count": 1, "format_count": 1,
         "has_videos": False, "has_extraartists": False, "run_id": rid},
    ])
    _write(ctx.clean_dir / "clean_masters.parquet", schemas.CLEAN_MASTERS, [
        {"master_id": 1, "title": "M1", "main_release_id": 1, "year": 2000,
         "decade": 2000, "year_precision": "year", "run_id": rid},
    ])
    _write(ctx.analytics_dir / "release_fact.parquet", schemas.RELEASE_FACT, [
        {"release_id": 1, "master_id": None, "title": None,
         "primary_artist_id": None, "primary_artist_name": None,
         "country": "UK", "released_raw": "2000", "year": 2000, "month": None,
         "day": None, "released_date": None, "released_date_precision": "year",
         "decade": 2000, "data_quality": "Correct", "track_count": 0,
         "artist_count": 1, "label_count": 1, "genre_count": 1, "style_count": 1,
         "format_count": 1, "primary_label_id": None, "primary_label_name": None,
         "primary_format_raw": None, "primary_format_group": "Vinyl",
         "format_quantity": None, "format_description_summary": None,
         "has_vinyl": True, "has_cd": False, "has_cassette": False,
         "has_digital": False, "has_box_set": False, "primary_genre": "Electronic",
         "style": "Techno", "style_order": 1, "run_id": rid},
    ])

    BuildMasterFactStep().run(ctx, manifest)
    entry = manifest.data["outputs"]["analytics"]["master_fact"]
    assert entry["row_count"] == 1
    assert entry["distinct_master_count"] == 1
