"""Atomic-rename DuckDB publisher: write to .new, swap on success.

See specs/001-discogs-etl/research.md R-03 and contracts/duckdb-schema.md.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from .file_utils import atomic_replace


_PUBLISHED_TABLES = ("release_fact", "release_artist_bridge", "release_label_bridge")

# Column list for release_unique_view, per contracts/duckdb-schema.md and source spec §10.
_RELEASE_UNIQUE_VIEW_COLUMNS = [
    "release_id",
    "master_id",
    "title",
    "primary_artist_id",
    "primary_artist_name",
    "country",
    "released_raw",
    "year",
    "month",
    "day",
    "released_date",
    "released_date_precision",
    "decade",
    "data_quality",
    "track_count",
    "artist_count",
    "label_count",
    "genre_count",
    "style_count",
    "format_count",
    "primary_label_id",
    "primary_label_name",
    "primary_format_raw",
    "primary_format_group",
    "format_quantity",
    "format_description_summary",
    "has_vinyl",
    "has_cd",
    "has_cassette",
    "has_digital",
    "has_box_set",
    "primary_genre",
    "run_id",
]


def publish(*, analytics_dir: str | Path, published_duckdb: str | Path) -> None:
    """Build a fresh DuckDB at <published_duckdb>.new from analytics parquet, then atomic-rename.

    Raises FileNotFoundError if any expected analytics parquet is missing.
    On any exception during the build, the .new file is removed; the canonical
    path is left untouched.
    """
    analytics = Path(analytics_dir)
    canonical = Path(published_duckdb)
    canonical.parent.mkdir(parents=True, exist_ok=True)

    parquets = {name: analytics / f"{name}.parquet" for name in _PUBLISHED_TABLES}
    missing = [str(p) for p in parquets.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing analytics parquet: {missing}")

    new_path = canonical.with_suffix(canonical.suffix + ".new")
    if new_path.exists():
        new_path.unlink()

    try:
        con = duckdb.connect(str(new_path))
        try:
            for name, path in parquets.items():
                con.execute(
                    f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path.as_posix()}')"
                )
            cols = ",\n  ".join(_RELEASE_UNIQUE_VIEW_COLUMNS)
            con.execute(
                "CREATE OR REPLACE VIEW release_unique_view AS\n"
                f"SELECT DISTINCT\n  {cols}\nFROM release_fact"
            )
        finally:
            con.close()
    except Exception:
        if new_path.exists():
            try:
                new_path.unlink()
            except OSError:
                pass
        raise

    atomic_replace(new_path, canonical)
