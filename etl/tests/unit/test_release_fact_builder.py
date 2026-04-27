"""End-to-end test of build_release_fact step against synthetic clean inputs.

We construct minimal in-memory clean Parquet files and run the builder against
them to validate release-fact grain (release × style; releases-with-no-styles
get one row with style_order=0, style=NULL) and the join contract from
contracts/duckdb-schema.md / data-model.md.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from discogs_etl.io import schemas
from discogs_etl.io.parquet_writer import BatchedParquetWriter
from discogs_etl.pipeline.context import LimitConfig, PathConfig, RunConfig, RunContext
from discogs_etl.pipeline.manifest import Manifest
from discogs_etl.steps.build_release_fact import BuildReleaseFactStep


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
    rid = "testrun"
    logger = logging.getLogger("discogs_etl.tests")
    ctx = RunContext(run_id=rid, snapshot_id=cfg.snapshot_id, config=cfg, logger=logger)
    for d in (ctx.clean_dir, ctx.analytics_dir, cfg.paths.manifests_dir):
        d.mkdir(parents=True, exist_ok=True)
    manifest = Manifest.create(
        ctx.manifest_path,
        run_id=rid,
        snapshot_id=cfg.snapshot_id,
        etl_version="0.0.0-test",
        started_at="2026-04-26T00:00:00Z",
        config_path=cfg.config_path,
        config_sha256=cfg.config_sha256,
    )
    return ctx, manifest


@pytest.fixture
def synthetic_clean(tmp_path: Path) -> Path:
    ctx, manifest = _make_ctx(tmp_path)
    rid = ctx.run_id
    # Two releases:
    #   R10 — no styles, single artist/label/genre, vinyl format
    #   R11 — two styles → 2 release_fact rows, single artist/label/genre, cd format
    _write(ctx.clean_dir / "clean_releases.parquet", schemas.CLEAN_RELEASES, [
        {
            "release_id": 10, "title": "R10", "country": "UK", "released_raw": "1999",
            "year": 1999, "month": None, "day": None, "released_date": None,
            "released_date_precision": "year", "decade": 1990, "data_quality": "Correct",
            "master_id": None, "master_is_main_release": None,
            "track_count": 0, "artist_count": 1, "label_count": 1, "genre_count": 1,
            "style_count": 0, "format_count": 1,
            "has_videos": False, "has_extraartists": False, "run_id": rid,
        },
        {
            "release_id": 11, "title": "R11", "country": "DE", "released_raw": "2010-05-20",
            "year": 2010, "month": 5, "day": 20, "released_date": __import__("datetime").date(2010, 5, 20),
            "released_date_precision": "day", "decade": 2010, "data_quality": "Correct",
            "master_id": None, "master_is_main_release": None,
            "track_count": 0, "artist_count": 1, "label_count": 1, "genre_count": 1,
            "style_count": 2, "format_count": 1,
            "has_videos": False, "has_extraartists": False, "run_id": rid,
        },
    ])
    _write(ctx.clean_dir / "clean_release_artists.parquet", schemas.CLEAN_RELEASE_ARTISTS, [
        {"release_id": 10, "artist_order": 1, "artist_id": 100, "artist_name": "A10",
         "artist_anv": None, "artist_join": None, "is_primary_artist": True, "run_id": rid},
        {"release_id": 11, "artist_order": 1, "artist_id": 101, "artist_name": "A11",
         "artist_anv": None, "artist_join": None, "is_primary_artist": True, "run_id": rid},
    ])
    _write(ctx.clean_dir / "clean_release_labels.parquet", schemas.CLEAN_RELEASE_LABELS, [
        {"release_id": 10, "label_order": 1, "label_id": 200, "label_name": "L10",
         "catno": "C10", "is_primary_label": True, "run_id": rid},
        {"release_id": 11, "label_order": 1, "label_id": 201, "label_name": "L11",
         "catno": "C11", "is_primary_label": True, "run_id": rid},
    ])
    _write(ctx.clean_dir / "clean_release_genres.parquet", schemas.CLEAN_RELEASE_GENRES, [
        {"release_id": 10, "genre_order": 1, "genre": "Rock", "is_primary_genre": True, "run_id": rid},
        {"release_id": 11, "genre_order": 1, "genre": "Electronic", "is_primary_genre": True, "run_id": rid},
    ])
    _write(ctx.clean_dir / "clean_release_styles.parquet", schemas.CLEAN_RELEASE_STYLES, [
        # R10 has no styles
        {"release_id": 11, "style_order": 1, "style": "Techno", "run_id": rid},
        {"release_id": 11, "style_order": 2, "style": "House", "run_id": rid},
    ])
    _write(ctx.clean_dir / "release_format_summary.parquet", schemas.RELEASE_FORMAT_SUMMARY, [
        {"release_id": 10, "primary_format_raw": "Vinyl", "primary_format_group": "Vinyl",
         "format_quantity": 1, "format_description_summary": "LP", "format_count": 1,
         "has_vinyl": True, "has_cd": False, "has_cassette": False,
         "has_digital": False, "has_box_set": False, "run_id": rid},
        {"release_id": 11, "primary_format_raw": "CD", "primary_format_group": "CD",
         "format_quantity": 1, "format_description_summary": "Album", "format_count": 1,
         "has_vinyl": False, "has_cd": True, "has_cassette": False,
         "has_digital": False, "has_box_set": False, "run_id": rid},
    ])
    BuildReleaseFactStep().run(ctx, manifest)
    return ctx.analytics_dir


def test_release_fact_grain_release_x_style(synthetic_clean: Path):
    rf = pq.read_table(synthetic_clean / "release_fact.parquet")
    rows = rf.to_pylist()
    # R10 (no styles) → 1 row, style_order=0, style=None.
    # R11 (2 styles)  → 2 rows, style_order=1 and 2.
    assert len(rows) == 3
    by_release = {(r["release_id"], r["style_order"]): r for r in rows}
    r10 = by_release[(10, 0)]
    assert r10["style"] is None
    assert r10["primary_genre"] == "Rock"
    assert r10["has_vinyl"] is True
    assert r10["primary_format_group"] == "Vinyl"
    r11_techno = by_release[(11, 1)]
    r11_house = by_release[(11, 2)]
    assert r11_techno["style"] == "Techno"
    assert r11_house["style"] == "House"
    for r in (r11_techno, r11_house):
        assert r["has_cd"] is True
        assert r["primary_genre"] == "Electronic"


def test_release_fact_columns_match_contract(synthetic_clean: Path):
    rf = pq.read_table(synthetic_clean / "release_fact.parquet")
    expected = set(schemas.RELEASE_FACT.names)
    assert set(rf.column_names) == expected


def test_release_fact_distinct_release_count_equals_input(synthetic_clean: Path):
    rf = pq.read_table(synthetic_clean / "release_fact.parquet")
    assert len({v for v in rf.column("release_id").to_pylist() if v is not None}) == 2
