"""Unit tests for individual DQ check helpers and severity classification."""
from __future__ import annotations

import pyarrow as pa

from discogs_etl.pipeline.manifest import CheckResult
from discogs_etl.quality.checks import (
    _check_at_most_one_primary,
    _check_in_set,
    _check_min_value,
    _check_no_null,
    _check_unique,
    _check_unique_pair,
)
from discogs_etl.quality.report import derive_status


def _t(rows, schema):
    return pa.Table.from_pylist(rows, schema=schema)


def test_no_null_passes_when_clean():
    schema = pa.schema([pa.field("x", pa.int64())])
    t = _t([{"x": 1}, {"x": 2}], schema)
    r = _check_no_null(t, "x", name="x_not_null", layer="staging", table_name="t")
    assert r.passed is True
    assert r.severity == "critical"


def test_no_null_fails_when_dirty():
    schema = pa.schema([pa.field("x", pa.int64())])
    t = _t([{"x": 1}, {"x": None}], schema)
    r = _check_no_null(t, "x", name="x_not_null", layer="staging", table_name="t")
    assert r.passed is False
    assert "1 null" in (r.details or "")


def test_unique_detects_dup():
    schema = pa.schema([pa.field("x", pa.int64())])
    t = _t([{"x": 1}, {"x": 1}], schema)
    r = _check_unique(t, "x", name="x_unique", layer="staging", table_name="t")
    assert r.passed is False


def test_unique_pair():
    schema = pa.schema([pa.field("a", pa.int64()), pa.field("b", pa.int32())])
    ok = _t([{"a": 1, "b": 1}, {"a": 1, "b": 2}], schema)
    bad = _t([{"a": 1, "b": 1}, {"a": 1, "b": 1}], schema)
    assert _check_unique_pair(ok, "a", "b", name="ab_unique", layer="x", table_name="t").passed
    assert not _check_unique_pair(bad, "a", "b", name="ab_unique", layer="x", table_name="t").passed


def test_in_set_passes_with_valid_values():
    schema = pa.schema([pa.field("g", pa.string())])
    t = _t([{"g": "Vinyl"}, {"g": "CD"}], schema)
    r = _check_in_set(t, "g", {"Vinyl", "CD"}, name="g_in_enum",
                     layer="clean", table_name="t")
    assert r.passed


def test_in_set_fails_on_unknown_value():
    schema = pa.schema([pa.field("g", pa.string())])
    t = _t([{"g": "Vinyl"}, {"g": "Quux"}], schema)
    r = _check_in_set(t, "g", {"Vinyl", "CD"}, name="g_in_enum",
                     layer="clean", table_name="t")
    assert not r.passed
    assert "Quux" in (r.details or "")


def test_at_most_one_primary_passes():
    schema = pa.schema([
        pa.field("rid", pa.int64()),
        pa.field("p", pa.bool_()),
    ])
    t = _t([
        {"rid": 1, "p": True}, {"rid": 1, "p": False},
        {"rid": 2, "p": True}, {"rid": 2, "p": False},
    ], schema)
    r = _check_at_most_one_primary(t, "rid", "p",
                                    name="at_most_one_primary",
                                    layer="clean", table_name="t")
    assert r.passed


def test_at_most_one_primary_fails():
    schema = pa.schema([
        pa.field("rid", pa.int64()),
        pa.field("p", pa.bool_()),
    ])
    t = _t([{"rid": 1, "p": True}, {"rid": 1, "p": True}], schema)
    r = _check_at_most_one_primary(t, "rid", "p",
                                    name="at_most_one_primary",
                                    layer="clean", table_name="t")
    assert not r.passed


def test_min_value_warning_severity_by_default():
    schema = pa.schema([pa.field("c", pa.int32())])
    t = _t([{"c": 0}, {"c": -1}], schema)
    r = _check_min_value(t, "c", 0,
                         name="c_non_negative", layer="clean", table_name="t")
    assert r.severity == "warning"
    assert not r.passed


def test_derive_status():
    crit_fail = CheckResult(name="a", layer="x", table="t", severity="critical",
                            passed=False, details="boom")
    warn_fail = CheckResult(name="b", layer="x", table="t", severity="warning",
                            passed=False, details="warn")
    ok = CheckResult(name="c", layer="x", table="t", severity="critical",
                     passed=True)
    assert derive_status([ok]) == "passed"
    assert derive_status([ok, warn_fail]) == "passed_with_warnings"
    assert derive_status([ok, crit_fail]) == "failed"
    assert derive_status([crit_fail, warn_fail]) == "failed"
