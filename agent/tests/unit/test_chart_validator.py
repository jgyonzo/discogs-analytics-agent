"""Tests for the chart_validator tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.chart_validator import ValidatorInput, chart_validator


def _exec_result(
    *,
    exit_code: int = 0,
    exception_type: str | None = None,
    result: dict | None = None,
) -> dict:
    return {
        "exit_code": exit_code,
        "stdout": "",
        "stderr": "",
        "duration_ms": 100,
        "result": result,
        "exception_type": exception_type,
        "exception_message": None,
    }


def _make_chart(tmp_path: Path) -> Path:
    p = tmp_path / "chart.html"
    p.write_text("<html><body>chart</body></html>")
    return p


def test_valid_chart_passes(tmp_path: Path) -> None:
    chart = _make_chart(tmp_path)
    er = _exec_result(result={
        "sql": "SELECT 1",
        "chart_path": str(chart),
        "dataframe_preview": [{"x": 1}],
        "row_count": 1,
        "chart_type": "bar",
    })
    with use_node("chart_validator"):
        out = chart_validator(ValidatorInput(
            execution_result=er,
            expected_chart_dir=str(tmp_path),
        ))
    assert out.valid is True
    assert out.errors == []


def test_missing_result_fails(tmp_path: Path) -> None:
    er = _exec_result(result=None)
    with use_node("chart_validator"):
        out = chart_validator(ValidatorInput(
            execution_result=er,
            expected_chart_dir=str(tmp_path),
        ))
    assert out.valid is False
    assert any(e.rule == "result_missing" for e in out.errors)


def test_chart_outside_dir_fails(tmp_path: Path) -> None:
    elsewhere = tmp_path.parent / "elsewhere.html"
    elsewhere.write_text("<html></html>")
    er = _exec_result(result={
        "sql": "SELECT 1",
        "chart_path": str(elsewhere),
        "dataframe_preview": [{"x": 1}],
        "row_count": 1,
        "chart_type": "bar",
    })
    with use_node("chart_validator"):
        out = chart_validator(ValidatorInput(
            execution_result=er,
            expected_chart_dir=str(tmp_path),
        ))
    assert out.valid is False
    assert any(e.rule == "chart_path_outside_dir" for e in out.errors)


def test_wrong_extension_fails(tmp_path: Path) -> None:
    p = tmp_path / "chart.png"
    p.write_text("nothtml")
    er = _exec_result(result={
        "sql": "SELECT 1",
        "chart_path": str(p),
        "dataframe_preview": [],
        "row_count": 0,
        "chart_type": "bar",
    })
    with use_node("chart_validator"):
        out = chart_validator(ValidatorInput(
            execution_result=er,
            expected_chart_dir=str(tmp_path),
        ))
    assert out.valid is False
    assert any(e.rule == "chart_extension" for e in out.errors)


def test_exception_marks_invalid(tmp_path: Path) -> None:
    chart = _make_chart(tmp_path)
    er = _exec_result(
        exit_code=1,
        exception_type="ValueError",
        result={
            "sql": "x",
            "chart_path": str(chart),
            "dataframe_preview": [],
            "row_count": 0,
            "chart_type": "bar",
        },
    )
    with use_node("chart_validator"):
        out = chart_validator(ValidatorInput(
            execution_result=er,
            expected_chart_dir=str(tmp_path),
        ))
    assert out.valid is False
    assert any(e.rule == "exception_raised" for e in out.errors)
    assert any(e.rule == "nonzero_exit" for e in out.errors)


def test_unknown_chart_type(tmp_path: Path) -> None:
    chart = _make_chart(tmp_path)
    er = _exec_result(result={
        "sql": "SELECT 1",
        "chart_path": str(chart),
        "dataframe_preview": [],
        "row_count": 0,
        "chart_type": "fancy_3d_unicorn",
    })
    with use_node("chart_validator"):
        out = chart_validator(ValidatorInput(
            execution_result=er,
            expected_chart_dir=str(tmp_path),
        ))
    assert out.valid is False
    assert any(e.rule == "chart_type_unknown" for e in out.errors)
