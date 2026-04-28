"""Data quality checks per source spec §12, with severity per FR-021.

In-memory implementations are the Fase 1 functions, kept unchanged at the
function-name level. Per spec ``002-etl-scaleup`` FR-014 / ``research.md``
R-05, four checks gain DuckDB-SQL siblings that route through
:mod:`discogs_etl.quality.dispatch` based on row count:

- ``_check_unique`` ↔ ``_check_unique_sql``
- ``_check_unique_pair`` ↔ ``_check_unique_pair_sql``
- ``_check_at_most_one_primary`` ↔ ``_check_at_most_one_primary_sql``
- ``_check_distinct_count_equals`` ↔ ``_check_distinct_count_equals_sql``

Both implementations of a given check return a CheckResult whose
``(name, layer, table, severity, passed)`` quintuple is identical for the
same input — :mod:`tests.unit.test_dq_check_parity` enforces this.

Other checks (``_check_no_null``, ``_check_in_set``, ``_check_min_value``)
are already O(1) or O(few) memory and stay in-memory only.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

import duckdb
import pyarrow.parquet as pq

from ..pipeline.manifest import CheckResult
from ..transforms.date_normalization import VALID_PRECISIONS
from ..transforms.format_normalization import VALID_FORMAT_GROUPS
from .dispatch import run_check


_DEFAULT_THRESHOLD = 10_000_000

VALID_YEAR_PRECISIONS: frozenset[str] = frozenset({"year", "unknown", "invalid"})


def _read(path: Path):
    return pq.read_table(path)


def _quote(identifier: str) -> str:
    """Quote a SQL identifier to survive reserved words like ``primary``."""
    return '"' + identifier.replace('"', '""') + '"'


def _src(parquet_path: Path) -> str:
    """Build a ``read_parquet('...')`` source clause for SQL queries."""
    return f"read_parquet('{Path(parquet_path).as_posix()}')"


# ---------- Single-column / streaming-trivial checks (in-memory only) ----------

def _check_no_null(table, col, *, name, layer, table_name) -> CheckResult:
    n_null = table.column(col).null_count
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=n_null == 0,
        details=None if n_null == 0 else f"{n_null} null value(s) in {col}",
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


def _check_min_value(
    table, col, min_value: int, *, name, layer, table_name, severity="warning",
) -> CheckResult:
    bad = sum(1 for v in table.column(col).to_pylist() if v is not None and v < min_value)
    return CheckResult(
        name=name, layer=layer, table=table_name, severity=severity,
        passed=bad == 0,
        details=None if bad == 0 else f"{bad} value(s) of {col} below {min_value}",
    )


# ---------- Dispatch-aware checks (in-memory + SQL siblings) ----------

def _check_unique(table, col, *, name, layer, table_name) -> CheckResult:
    counts = Counter(table.column(col).to_pylist())
    dups = [v for v, c in counts.items() if c > 1]
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=not dups,
        details=None if not dups else f"{len(dups)} duplicate value(s) in {col}; e.g. {dups[:5]}",
    )


def _check_unique_sql(parquet_path: Path, col, *, name, layer, table_name) -> CheckResult:
    qcol = _quote(col)
    src = _src(parquet_path)
    con = duckdb.connect(":memory:")
    try:
        sample = con.execute(
            f"SELECT {qcol} FROM {src} "
            f"GROUP BY {qcol} HAVING COUNT(*) > 1 LIMIT 5"
        ).fetchall()
        dup_count = con.execute(
            f"SELECT COUNT(*) FROM ("
            f"  SELECT {qcol} FROM {src} "
            f"  GROUP BY {qcol} HAVING COUNT(*) > 1"
            f")"
        ).fetchone()[0]
    finally:
        con.close()
    passed = dup_count == 0
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=passed,
        details=None if passed
        else f"{dup_count} duplicate value(s) in {col}; e.g. {[r[0] for r in sample]}",
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


def _check_unique_pair_sql(parquet_path: Path, c1, c2, *, name, layer, table_name) -> CheckResult:
    qc1, qc2 = _quote(c1), _quote(c2)
    src = _src(parquet_path)
    con = duckdb.connect(":memory:")
    try:
        sample = con.execute(
            f"SELECT {qc1}, {qc2} FROM {src} "
            f"GROUP BY 1, 2 HAVING COUNT(*) > 1 LIMIT 3"
        ).fetchall()
        dup_count = con.execute(
            f"SELECT COUNT(*) FROM ("
            f"  SELECT {qc1}, {qc2} FROM {src} "
            f"  GROUP BY 1, 2 HAVING COUNT(*) > 1"
            f")"
        ).fetchone()[0]
    finally:
        con.close()
    passed = dup_count == 0
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=passed,
        details=None if passed
        else f"{dup_count} duplicate pair(s) of ({c1}, {c2}); e.g. {sample}",
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


def _check_at_most_one_primary_sql(
    parquet_path: Path, group_col, flag_col, *, name, layer, table_name,
) -> CheckResult:
    qg, qf = _quote(group_col), _quote(flag_col)
    src = _src(parquet_path)
    con = duckdb.connect(":memory:")
    try:
        sample = con.execute(
            f"SELECT {qg} FROM {src} "
            f"WHERE {qf} GROUP BY 1 HAVING COUNT(*) > 1 LIMIT 5"
        ).fetchall()
        bad_count = con.execute(
            f"SELECT COUNT(*) FROM ("
            f"  SELECT {qg} FROM {src} "
            f"  WHERE {qf} GROUP BY 1 HAVING COUNT(*) > 1"
            f")"
        ).fetchone()[0]
    finally:
        con.close()
    passed = bad_count == 0
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=passed,
        details=None if passed
        else f"{bad_count} {group_col}(s) with more than one {flag_col}=true; e.g. {[r[0] for r in sample]}",
    )


def _check_distinct_count_equals(
    table, col, *, expected_count: int, name, layer, table_name,
) -> CheckResult:
    distinct = len({v for v in table.column(col).to_pylist() if v is not None})
    passed = distinct == expected_count
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=passed,
        details=None if passed
        else f"distinct {col}={distinct} != expected={expected_count}",
    )


def _check_distinct_count_equals_sql(
    parquet_path: Path, col, *, expected_count: int, name, layer, table_name,
) -> CheckResult:
    qcol = _quote(col)
    src = _src(parquet_path)
    con = duckdb.connect(":memory:")
    try:
        distinct = con.execute(
            f"SELECT COUNT(DISTINCT {qcol}) FROM {src}"
        ).fetchone()[0]
    finally:
        con.close()
    passed = distinct == expected_count
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=passed,
        details=None if passed
        else f"distinct {col}={distinct} != expected={expected_count}",
    )


# ---------- Layer entrypoints (now threshold-aware) ----------

def run_staging_checks(
    staging_dir: Path, *, threshold: int = _DEFAULT_THRESHOLD,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    rel_path = staging_dir / "stg_releases.parquet"
    rel = _read(rel_path)
    results.append(_check_no_null(rel, "release_id",
                                   name="stg_releases.release_id_not_null",
                                   layer="staging", table_name="stg_releases"))
    results.append(run_check(
        rel_path, _check_unique, _check_unique_sql, "release_id",
        threshold=threshold,
        name="stg_releases.release_id_unique",
        layer="staging", table_name="stg_releases",
    ))
    results.append(CheckResult(
        name="stg_releases.row_count_positive",
        layer="staging", table="stg_releases", severity="critical",
        passed=rel.num_rows > 0,
        details=None if rel.num_rows > 0 else "0 rows in stg_releases",
    ))

    # Fase 4: optional masters / artists staging checks.
    masters_path = staging_dir / "stg_masters.parquet"
    if masters_path.exists():
        masters_table = _read(masters_path)
        results.append(_check_no_null(
            masters_table, "master_id",
            name="stg_masters.master_id_not_null",
            layer="staging", table_name="stg_masters",
        ))
        results.append(run_check(
            masters_path, _check_unique, _check_unique_sql, "master_id",
            threshold=threshold,
            name="stg_masters.master_id_unique",
            layer="staging", table_name="stg_masters",
        ))

    artists_path = staging_dir / "stg_artists.parquet"
    if artists_path.exists():
        artists_table = _read(artists_path)
        results.append(_check_no_null(
            artists_table, "artist_id",
            name="stg_artists.artist_id_not_null",
            layer="staging", table_name="stg_artists",
        ))
        results.append(run_check(
            artists_path, _check_unique, _check_unique_sql, "artist_id",
            threshold=threshold,
            name="stg_artists.artist_id_unique",
            layer="staging", table_name="stg_artists",
        ))

    return results


def run_clean_checks(
    clean_dir: Path, *, threshold: int = _DEFAULT_THRESHOLD,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    rel_path = clean_dir / "clean_releases.parquet"
    rel = _read(rel_path)
    results.append(run_check(
        rel_path, _check_unique, _check_unique_sql, "release_id",
        threshold=threshold,
        name="clean_releases.release_id_unique",
        layer="clean", table_name="clean_releases",
    ))
    results.append(_check_in_set(rel, "released_date_precision", VALID_PRECISIONS,
                                  name="clean_releases.released_date_precision_in_enum",
                                  layer="clean", table_name="clean_releases"))
    for col in ("track_count", "artist_count", "label_count",
                "genre_count", "style_count", "format_count"):
        results.append(_check_min_value(rel, col, 0,
                                         name=f"clean_releases.{col}_non_negative",
                                         layer="clean", table_name="clean_releases"))

    fmt_path = clean_dir / "clean_release_formats.parquet"
    fmt = _read(fmt_path)
    results.append(_check_no_null(fmt, "release_id",
                                   name="clean_release_formats.release_id_not_null",
                                   layer="clean", table_name="clean_release_formats"))
    results.append(run_check(
        fmt_path, _check_unique_pair, _check_unique_pair_sql,
        "release_id", "format_order",
        threshold=threshold,
        name="clean_release_formats.unique_release_id_format_order",
        layer="clean", table_name="clean_release_formats",
    ))
    results.append(_check_in_set(fmt, "format_group", VALID_FORMAT_GROUPS,
                                  name="clean_release_formats.format_group_in_enum",
                                  layer="clean", table_name="clean_release_formats"))
    for col in ("is_primary_format", "is_vinyl_format", "is_cd_format",
                "is_cassette_format", "is_digital_format", "is_box_set_format"):
        results.append(_check_no_null(fmt, col,
                                       name=f"clean_release_formats.{col}_not_null",
                                       layer="clean", table_name="clean_release_formats"))
    results.append(run_check(
        fmt_path, _check_at_most_one_primary, _check_at_most_one_primary_sql,
        "release_id", "is_primary_format",
        threshold=threshold,
        name="clean_release_formats.at_most_one_primary",
        layer="clean", table_name="clean_release_formats",
    ))

    summary_path = clean_dir / "release_format_summary.parquet"
    summary = _read(summary_path)
    results.append(run_check(
        summary_path, _check_unique, _check_unique_sql, "release_id",
        threshold=threshold,
        name="release_format_summary.release_id_unique",
        layer="clean", table_name="release_format_summary",
    ))
    results.append(_check_in_set(summary, "primary_format_group", VALID_FORMAT_GROUPS,
                                  name="release_format_summary.primary_format_group_in_enum",
                                  layer="clean", table_name="release_format_summary"))
    for col in ("has_vinyl", "has_cd", "has_cassette", "has_digital", "has_box_set"):
        results.append(_check_no_null(summary, col,
                                       name=f"release_format_summary.{col}_not_null",
                                       layer="clean", table_name="release_format_summary"))

    # Fase 4: optional clean_masters / clean_artists checks.
    cm_path = clean_dir / "clean_masters.parquet"
    if cm_path.exists():
        cm = _read(cm_path)
        results.append(run_check(
            cm_path, _check_unique, _check_unique_sql, "master_id",
            threshold=threshold,
            name="clean_masters.master_id_unique",
            layer="clean", table_name="clean_masters",
        ))
        results.append(_check_in_set(
            cm, "year_precision", VALID_YEAR_PRECISIONS,
            name="clean_masters.year_precision_in_enum",
            layer="clean", table_name="clean_masters",
        ))

    ca_path = clean_dir / "clean_artists.parquet"
    if ca_path.exists():
        results.append(run_check(
            ca_path, _check_unique, _check_unique_sql, "artist_id",
            threshold=threshold,
            name="clean_artists.artist_id_unique",
            layer="clean", table_name="clean_artists",
        ))

    return results


def _check_sum_release_count_equals(
    master_fact_path: Path, clean_releases_path: Path,
    *, name, layer, table_name,
) -> CheckResult:
    """Cross-table consistency check (FR-015 / SC-003).

    SQL-only standalone helper (per spec ``003-masters-artists`` /
    ``research.md`` R-05): asserts
    ``SUM(master_fact.release_count) = COUNT(clean_releases WHERE master_id IS NOT NULL)``.
    """
    src_mf = _src(master_fact_path)
    src_cr = _src(clean_releases_path)
    con = duckdb.connect(":memory:")
    try:
        sum_ = con.execute(
            f"SELECT COALESCE(SUM(release_count), 0) FROM {src_mf}"
        ).fetchone()[0]
        cnt_ = con.execute(
            f"SELECT COUNT(*) FROM {src_cr} WHERE master_id IS NOT NULL"
        ).fetchone()[0]
    finally:
        con.close()
    passed = int(sum_) == int(cnt_)
    return CheckResult(
        name=name, layer=layer, table=table_name, severity="critical",
        passed=passed,
        details=None if passed
        else f"SUM(master_fact.release_count)={sum_} != "
             f"COUNT(clean_releases WHERE master_id IS NOT NULL)={cnt_}",
    )


def run_analytics_checks(
    analytics_dir: Path, clean_releases_row_count: int,
    *, threshold: int = _DEFAULT_THRESHOLD,
    clean_dir: Path | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    rf_path = analytics_dir / "release_fact.parquet"
    rf = _read(rf_path)
    results.append(_check_no_null(rf, "release_id",
                                   name="release_fact.release_id_not_null",
                                   layer="analytics", table_name="release_fact"))
    results.append(run_check(
        rf_path, _check_unique_pair, _check_unique_pair_sql,
        "release_id", "style_order",
        threshold=threshold,
        name="release_fact.unique_release_id_style_order",
        layer="analytics", table_name="release_fact",
    ))
    results.append(_check_in_set(rf, "primary_format_group", VALID_FORMAT_GROUPS,
                                  name="release_fact.primary_format_group_in_enum",
                                  layer="analytics", table_name="release_fact"))
    for col in ("has_vinyl", "has_cd", "has_cassette", "has_digital", "has_box_set"):
        results.append(_check_no_null(rf, col,
                                       name=f"release_fact.{col}_not_null",
                                       layer="analytics", table_name="release_fact"))
    results.append(run_check(
        rf_path, _check_distinct_count_equals, _check_distinct_count_equals_sql,
        "release_id",
        threshold=threshold,
        expected_count=clean_releases_row_count,
        name="release_fact.distinct_release_count_equals_clean_releases",
        layer="analytics", table_name="release_fact",
    ))

    rab_path = analytics_dir / "release_artist_bridge.parquet"
    results.append(_check_no_null(_read(rab_path), "release_id",
                                   name="release_artist_bridge.release_id_not_null",
                                   layer="analytics", table_name="release_artist_bridge"))
    results.append(run_check(
        rab_path, _check_unique_pair, _check_unique_pair_sql,
        "release_id", "artist_order",
        threshold=threshold,
        name="release_artist_bridge.unique_release_id_artist_order",
        layer="analytics", table_name="release_artist_bridge",
    ))
    results.append(run_check(
        rab_path, _check_at_most_one_primary, _check_at_most_one_primary_sql,
        "release_id", "is_primary_artist",
        threshold=threshold,
        name="release_artist_bridge.at_most_one_primary",
        layer="analytics", table_name="release_artist_bridge",
    ))

    rlb_path = analytics_dir / "release_label_bridge.parquet"
    results.append(_check_no_null(_read(rlb_path), "release_id",
                                   name="release_label_bridge.release_id_not_null",
                                   layer="analytics", table_name="release_label_bridge"))
    results.append(run_check(
        rlb_path, _check_unique_pair, _check_unique_pair_sql,
        "release_id", "label_order",
        threshold=threshold,
        name="release_label_bridge.unique_release_id_label_order",
        layer="analytics", table_name="release_label_bridge",
    ))
    results.append(run_check(
        rlb_path, _check_at_most_one_primary, _check_at_most_one_primary_sql,
        "release_id", "is_primary_label",
        threshold=threshold,
        name="release_label_bridge.at_most_one_primary",
        layer="analytics", table_name="release_label_bridge",
    ))

    # Fase 4: optional master_fact checks.
    mf_path = analytics_dir / "master_fact.parquet"
    if mf_path.exists():
        mf = _read(mf_path)
        results.append(run_check(
            mf_path, _check_unique, _check_unique_sql, "master_id",
            threshold=threshold,
            name="master_fact.master_id_unique",
            layer="analytics", table_name="master_fact",
        ))
        results.append(_check_min_value(
            mf, "release_count", 0,
            name="master_fact.release_count_non_negative",
            layer="analytics", table_name="master_fact",
        ))
        # Cross-table consistency: sum-equals-count via the standalone helper.
        # Caller (steps/quality_checks.py) passes clean_dir explicitly to
        # avoid fragile path derivation across spec-versioned layouts.
        if clean_dir is not None:
            cr_path = Path(clean_dir) / "clean_releases.parquet"
            if cr_path.exists():
                results.append(_check_sum_release_count_equals(
                    mf_path, cr_path,
                    name="master_fact.sum_release_count_equals_clean_releases_with_master_id",
                    layer="analytics", table_name="master_fact",
                ))

    return results
