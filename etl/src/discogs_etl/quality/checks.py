"""Data quality checks per source spec §12, with severity per FR-021."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as pq

from ..pipeline.manifest import CheckResult
from ..transforms.date_normalization import VALID_PRECISIONS
from ..transforms.format_normalization import VALID_FORMAT_GROUPS


def _read(path: Path):
    return pq.read_table(path)


def _check_no_null(table, col, *, name, layer, table_name) -> CheckResult:
    n_null = table.column(col).null_count
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=n_null == 0,
        details=None if n_null == 0 else f"{n_null} null value(s) in {col}",
    )


def _check_unique(table, col, *, name, layer, table_name) -> CheckResult:
    counts = Counter(table.column(col).to_pylist())
    dups = [v for v, c in counts.items() if c > 1]
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=not dups,
        details=None if not dups else f"{len(dups)} duplicate value(s) in {col}; e.g. {dups[:5]}",
    )


def _check_unique_pair(table, c1, c2, *, name, layer, table_name) -> CheckResult:
    pairs = list(zip(table.column(c1).to_pylist(), table.column(c2).to_pylist()))
    counts = Counter(pairs)
    dups = [p for p, c in counts.items() if c > 1]
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=not dups,
        details=None if not dups else f"{len(dups)} duplicate pair(s) of ({c1}, {c2}); e.g. {dups[:3]}",
    )


def _check_in_set(
    table, col, allowed: Iterable[str], *, name, layer, table_name, severity="critical",
) -> CheckResult:
    allowed_set = frozenset(allowed)
    bad = sorted({v for v in table.column(col).to_pylist() if v is not None and v not in allowed_set})
    return CheckResult(
        name=name, layer=layer, table=table_name, severity=severity,
        passed=not bad,
        details=None if not bad else f"{len(bad)} unrecognized value(s) in {col}: {bad[:10]}",
    )


def _check_at_most_one_primary(
    table, group_col, flag_col, *, name, layer, table_name,
) -> CheckResult:
    flags = table.column(flag_col).to_pylist()
    groups = table.column(group_col).to_pylist()
    counter: Counter = Counter()
    for g, f in zip(groups, flags):
        if f:
            counter[g] += 1
    bad = [g for g, c in counter.items() if c > 1]
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=not bad,
        details=None if not bad else f"{len(bad)} {group_col}(s) with more than one {flag_col}=true; e.g. {bad[:5]}",
    )


def _check_min_value(
    table, col, min_value: int, *, name, layer, table_name, severity="warning",
) -> CheckResult:
    bad = sum(1 for v in table.column(col).to_pylist() if v is not None and v < min_value)
    return CheckResult(
        name=name, layer=layer, table=table_name, severity=severity,
        passed=bad == 0,
        details=None if bad == 0 else f"{bad} value(s) of {col} below {min_value}",
    )


# ----- Layer entrypoints -----

def run_staging_checks(staging_dir: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    rel = _read(staging_dir / "stg_releases.parquet")
    results.append(_check_no_null(rel, "release_id",
                                   name="stg_releases.release_id_not_null",
                                   layer="staging", table_name="stg_releases"))
    results.append(_check_unique(rel, "release_id",
                                  name="stg_releases.release_id_unique",
                                  layer="staging", table_name="stg_releases"))
    results.append(CheckResult(
        name="stg_releases.row_count_positive",
        layer="staging", table="stg_releases", severity="critical",
        passed=rel.num_rows > 0,
        details=None if rel.num_rows > 0 else "0 rows in stg_releases",
    ))
    return results


def run_clean_checks(clean_dir: Path) -> list[CheckResult]:
    results: list[CheckResult] = []

    rel = _read(clean_dir / "clean_releases.parquet")
    results.append(_check_unique(rel, "release_id",
                                  name="clean_releases.release_id_unique",
                                  layer="clean", table_name="clean_releases"))
    results.append(_check_in_set(rel, "released_date_precision", VALID_PRECISIONS,
                                  name="clean_releases.released_date_precision_in_enum",
                                  layer="clean", table_name="clean_releases"))
    for col in ("track_count", "artist_count", "label_count",
                "genre_count", "style_count", "format_count"):
        results.append(_check_min_value(rel, col, 0,
                                         name=f"clean_releases.{col}_non_negative",
                                         layer="clean", table_name="clean_releases"))

    fmt = _read(clean_dir / "clean_release_formats.parquet")
    results.append(_check_no_null(fmt, "release_id",
                                   name="clean_release_formats.release_id_not_null",
                                   layer="clean", table_name="clean_release_formats"))
    results.append(_check_unique_pair(fmt, "release_id", "format_order",
                                       name="clean_release_formats.unique_release_id_format_order",
                                       layer="clean", table_name="clean_release_formats"))
    results.append(_check_in_set(fmt, "format_group", VALID_FORMAT_GROUPS,
                                  name="clean_release_formats.format_group_in_enum",
                                  layer="clean", table_name="clean_release_formats"))
    for col in ("is_primary_format", "is_vinyl_format", "is_cd_format",
                "is_cassette_format", "is_digital_format", "is_box_set_format"):
        results.append(_check_no_null(fmt, col,
                                       name=f"clean_release_formats.{col}_not_null",
                                       layer="clean", table_name="clean_release_formats"))
    results.append(_check_at_most_one_primary(fmt, "release_id", "is_primary_format",
                                                name="clean_release_formats.at_most_one_primary",
                                                layer="clean", table_name="clean_release_formats"))

    summary = _read(clean_dir / "release_format_summary.parquet")
    results.append(_check_unique(summary, "release_id",
                                  name="release_format_summary.release_id_unique",
                                  layer="clean", table_name="release_format_summary"))
    results.append(_check_in_set(summary, "primary_format_group", VALID_FORMAT_GROUPS,
                                  name="release_format_summary.primary_format_group_in_enum",
                                  layer="clean", table_name="release_format_summary"))
    for col in ("has_vinyl", "has_cd", "has_cassette", "has_digital", "has_box_set"):
        results.append(_check_no_null(summary, col,
                                       name=f"release_format_summary.{col}_not_null",
                                       layer="clean", table_name="release_format_summary"))

    return results


def run_analytics_checks(analytics_dir: Path, clean_releases_row_count: int) -> list[CheckResult]:
    results: list[CheckResult] = []

    rf = _read(analytics_dir / "release_fact.parquet")
    results.append(_check_no_null(rf, "release_id",
                                   name="release_fact.release_id_not_null",
                                   layer="analytics", table_name="release_fact"))
    results.append(_check_unique_pair(rf, "release_id", "style_order",
                                       name="release_fact.unique_release_id_style_order",
                                       layer="analytics", table_name="release_fact"))
    results.append(_check_in_set(rf, "primary_format_group", VALID_FORMAT_GROUPS,
                                  name="release_fact.primary_format_group_in_enum",
                                  layer="analytics", table_name="release_fact"))
    for col in ("has_vinyl", "has_cd", "has_cassette", "has_digital", "has_box_set"):
        results.append(_check_no_null(rf, col,
                                       name=f"release_fact.{col}_not_null",
                                       layer="analytics", table_name="release_fact"))
    distinct = len({v for v in rf.column("release_id").to_pylist() if v is not None})
    results.append(CheckResult(
        name="release_fact.distinct_release_count_equals_clean_releases",
        layer="analytics", table="release_fact", severity="critical",
        passed=distinct == clean_releases_row_count,
        details=(None if distinct == clean_releases_row_count
                 else f"distinct release_id={distinct} != clean_releases row_count={clean_releases_row_count}"),
    ))

    rab = _read(analytics_dir / "release_artist_bridge.parquet")
    results.append(_check_no_null(rab, "release_id",
                                   name="release_artist_bridge.release_id_not_null",
                                   layer="analytics", table_name="release_artist_bridge"))
    results.append(_check_unique_pair(rab, "release_id", "artist_order",
                                       name="release_artist_bridge.unique_release_id_artist_order",
                                       layer="analytics", table_name="release_artist_bridge"))
    results.append(_check_at_most_one_primary(rab, "release_id", "is_primary_artist",
                                                name="release_artist_bridge.at_most_one_primary",
                                                layer="analytics", table_name="release_artist_bridge"))

    rlb = _read(analytics_dir / "release_label_bridge.parquet")
    results.append(_check_no_null(rlb, "release_id",
                                   name="release_label_bridge.release_id_not_null",
                                   layer="analytics", table_name="release_label_bridge"))
    results.append(_check_unique_pair(rlb, "release_id", "label_order",
                                       name="release_label_bridge.unique_release_id_label_order",
                                       layer="analytics", table_name="release_label_bridge"))
    results.append(_check_at_most_one_primary(rlb, "release_id", "is_primary_label",
                                                name="release_label_bridge.at_most_one_primary",
                                                layer="analytics", table_name="release_label_bridge"))

    return results
