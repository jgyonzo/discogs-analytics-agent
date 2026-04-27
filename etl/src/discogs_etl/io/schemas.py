"""Pyarrow schemas for every Parquet output table.

Authoritative source: source spec sections 6 (staging), 7 (clean),
8 (release_format_summary), 9 (analytics).
"""
from __future__ import annotations

import pyarrow as pa


# ----- Staging (source spec §6) -----

STG_RELEASES = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("title", pa.string(), nullable=True),
    pa.field("country", pa.string(), nullable=True),
    pa.field("released_raw", pa.string(), nullable=True),
    pa.field("notes", pa.string(), nullable=True),
    pa.field("data_quality", pa.string(), nullable=True),
    pa.field("master_id", pa.int64(), nullable=True),
    pa.field("master_is_main_release", pa.bool_(), nullable=True),
    pa.field("status", pa.string(), nullable=True),
    # Presence flags — extension over source spec §6.1 to make clean §7.1
    # has_videos / has_extraartists derivable without re-reading XML.
    pa.field("has_videos", pa.bool_(), nullable=False),
    pa.field("has_extraartists", pa.bool_(), nullable=False),
    pa.field("source_file", pa.string(), nullable=False),
    pa.field("parsed_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_ARTISTS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("artist_order", pa.int32(), nullable=False),
    pa.field("artist_id", pa.int64(), nullable=True),
    pa.field("artist_name", pa.string(), nullable=True),
    pa.field("artist_anv", pa.string(), nullable=True),
    pa.field("artist_join", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_LABELS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("label_order", pa.int32(), nullable=False),
    pa.field("label_id", pa.int64(), nullable=True),
    pa.field("label_name", pa.string(), nullable=True),
    pa.field("catno", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_FORMATS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("format_order", pa.int32(), nullable=False),
    pa.field("format_name", pa.string(), nullable=True),
    pa.field("format_qty_raw", pa.string(), nullable=True),
    pa.field("format_text", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_FORMAT_DESCRIPTIONS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("format_order", pa.int32(), nullable=False),
    pa.field("description_order", pa.int32(), nullable=False),
    pa.field("description", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_GENRES = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("genre_order", pa.int32(), nullable=False),
    pa.field("genre", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_STYLES = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("style_order", pa.int32(), nullable=False),
    pa.field("style", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])

STG_RELEASE_TRACKS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("track_order", pa.int32(), nullable=False),
    pa.field("position", pa.string(), nullable=True),
    pa.field("title", pa.string(), nullable=True),
    pa.field("duration_raw", pa.string(), nullable=True),
    pa.field("track_type", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])


# ----- Clean (source spec §7) -----

CLEAN_RELEASES = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("title", pa.string(), nullable=True),
    pa.field("country", pa.string(), nullable=True),
    pa.field("released_raw", pa.string(), nullable=True),
    pa.field("year", pa.int32(), nullable=True),
    pa.field("month", pa.int32(), nullable=True),
    pa.field("day", pa.int32(), nullable=True),
    pa.field("released_date", pa.date32(), nullable=True),
    pa.field("released_date_precision", pa.string(), nullable=False),
    pa.field("decade", pa.int32(), nullable=True),
    pa.field("data_quality", pa.string(), nullable=True),
    pa.field("master_id", pa.int64(), nullable=True),
    pa.field("master_is_main_release", pa.bool_(), nullable=True),
    pa.field("track_count", pa.int32(), nullable=False),
    pa.field("artist_count", pa.int32(), nullable=False),
    pa.field("label_count", pa.int32(), nullable=False),
    pa.field("genre_count", pa.int32(), nullable=False),
    pa.field("style_count", pa.int32(), nullable=False),
    pa.field("format_count", pa.int32(), nullable=False),
    pa.field("has_videos", pa.bool_(), nullable=False),
    pa.field("has_extraartists", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

CLEAN_RELEASE_ARTISTS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("artist_order", pa.int32(), nullable=False),
    pa.field("artist_id", pa.int64(), nullable=True),
    pa.field("artist_name", pa.string(), nullable=True),
    pa.field("artist_anv", pa.string(), nullable=True),
    pa.field("artist_join", pa.string(), nullable=True),
    pa.field("is_primary_artist", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

CLEAN_RELEASE_LABELS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("label_order", pa.int32(), nullable=False),
    pa.field("label_id", pa.int64(), nullable=True),
    pa.field("label_name", pa.string(), nullable=True),
    pa.field("catno", pa.string(), nullable=True),
    pa.field("is_primary_label", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

CLEAN_RELEASE_FORMATS = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("format_order", pa.int32(), nullable=False),
    pa.field("format_name_raw", pa.string(), nullable=True),
    pa.field("format_group", pa.string(), nullable=False),
    pa.field("format_quantity", pa.int32(), nullable=True),
    pa.field("format_text", pa.string(), nullable=True),
    pa.field("format_description_summary", pa.string(), nullable=True),
    pa.field("is_primary_format", pa.bool_(), nullable=False),
    pa.field("is_vinyl_format", pa.bool_(), nullable=False),
    pa.field("is_cd_format", pa.bool_(), nullable=False),
    pa.field("is_cassette_format", pa.bool_(), nullable=False),
    pa.field("is_digital_format", pa.bool_(), nullable=False),
    pa.field("is_box_set_format", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

CLEAN_RELEASE_GENRES = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("genre_order", pa.int32(), nullable=False),
    pa.field("genre", pa.string(), nullable=True),
    pa.field("is_primary_genre", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

CLEAN_RELEASE_STYLES = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("style_order", pa.int32(), nullable=False),
    pa.field("style", pa.string(), nullable=True),
    pa.field("run_id", pa.string(), nullable=False),
])


# ----- Summary (source spec §8) -----

RELEASE_FORMAT_SUMMARY = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("primary_format_raw", pa.string(), nullable=True),
    pa.field("primary_format_group", pa.string(), nullable=False),
    pa.field("format_quantity", pa.int32(), nullable=True),
    pa.field("format_description_summary", pa.string(), nullable=True),
    pa.field("format_count", pa.int32(), nullable=False),
    pa.field("has_vinyl", pa.bool_(), nullable=False),
    pa.field("has_cd", pa.bool_(), nullable=False),
    pa.field("has_cassette", pa.bool_(), nullable=False),
    pa.field("has_digital", pa.bool_(), nullable=False),
    pa.field("has_box_set", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])


# ----- Analytics (source spec §9) -----

RELEASE_FACT = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("master_id", pa.int64(), nullable=True),
    pa.field("title", pa.string(), nullable=True),
    pa.field("primary_artist_id", pa.int64(), nullable=True),
    pa.field("primary_artist_name", pa.string(), nullable=True),
    pa.field("country", pa.string(), nullable=True),
    pa.field("released_raw", pa.string(), nullable=True),
    pa.field("year", pa.int32(), nullable=True),
    pa.field("month", pa.int32(), nullable=True),
    pa.field("day", pa.int32(), nullable=True),
    pa.field("released_date", pa.date32(), nullable=True),
    pa.field("released_date_precision", pa.string(), nullable=False),
    pa.field("decade", pa.int32(), nullable=True),
    pa.field("data_quality", pa.string(), nullable=True),
    pa.field("track_count", pa.int32(), nullable=False),
    pa.field("artist_count", pa.int32(), nullable=False),
    pa.field("label_count", pa.int32(), nullable=False),
    pa.field("genre_count", pa.int32(), nullable=False),
    pa.field("style_count", pa.int32(), nullable=False),
    pa.field("format_count", pa.int32(), nullable=False),
    pa.field("primary_label_id", pa.int64(), nullable=True),
    pa.field("primary_label_name", pa.string(), nullable=True),
    pa.field("primary_format_raw", pa.string(), nullable=True),
    pa.field("primary_format_group", pa.string(), nullable=False),
    pa.field("format_quantity", pa.int32(), nullable=True),
    pa.field("format_description_summary", pa.string(), nullable=True),
    pa.field("has_vinyl", pa.bool_(), nullable=False),
    pa.field("has_cd", pa.bool_(), nullable=False),
    pa.field("has_cassette", pa.bool_(), nullable=False),
    pa.field("has_digital", pa.bool_(), nullable=False),
    pa.field("has_box_set", pa.bool_(), nullable=False),
    pa.field("primary_genre", pa.string(), nullable=True),
    pa.field("style", pa.string(), nullable=True),
    pa.field("style_order", pa.int32(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

RELEASE_ARTIST_BRIDGE = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("artist_id", pa.int64(), nullable=True),
    pa.field("artist_name", pa.string(), nullable=True),
    pa.field("artist_order", pa.int32(), nullable=False),
    pa.field("artist_anv", pa.string(), nullable=True),
    pa.field("artist_join", pa.string(), nullable=True),
    pa.field("is_primary_artist", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])

RELEASE_LABEL_BRIDGE = pa.schema([
    pa.field("release_id", pa.int64(), nullable=False),
    pa.field("label_id", pa.int64(), nullable=True),
    pa.field("label_name", pa.string(), nullable=True),
    pa.field("label_order", pa.int32(), nullable=False),
    pa.field("catno", pa.string(), nullable=True),
    pa.field("is_primary_label", pa.bool_(), nullable=False),
    pa.field("run_id", pa.string(), nullable=False),
])
