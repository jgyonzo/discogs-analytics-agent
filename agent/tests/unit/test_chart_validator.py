"""Tests for the chart_validator tool."""

from __future__ import annotations

from pathlib import Path

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
    er = _exec_result(
        result={
            "sql": "SELECT 1",
            "chart_path": str(chart),
            "dataframe_preview": [{"x": 1}],
            "row_count": 1,
            "chart_type": "bar",
        }
    )
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is True
    assert out.errors == []


def test_missing_result_fails(tmp_path: Path) -> None:
    er = _exec_result(result=None)
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is False
    assert any(e.rule == "result_missing" for e in out.errors)


def test_chart_outside_dir_fails(tmp_path: Path) -> None:
    elsewhere = tmp_path.parent / "elsewhere.html"
    elsewhere.write_text("<html></html>")
    er = _exec_result(
        result={
            "sql": "SELECT 1",
            "chart_path": str(elsewhere),
            "dataframe_preview": [{"x": 1}],
            "row_count": 1,
            "chart_type": "bar",
        }
    )
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is False
    assert any(e.rule == "chart_path_outside_dir" for e in out.errors)


def test_wrong_extension_fails(tmp_path: Path) -> None:
    p = tmp_path / "chart.png"
    p.write_text("nothtml")
    er = _exec_result(
        result={
            "sql": "SELECT 1",
            "chart_path": str(p),
            "dataframe_preview": [],
            "row_count": 0,
            "chart_type": "bar",
        }
    )
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
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
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is False
    assert any(e.rule == "exception_raised" for e in out.errors)
    assert any(e.rule == "nonzero_exit" for e in out.errors)


def test_unknown_chart_type(tmp_path: Path) -> None:
    chart = _make_chart(tmp_path)
    er = _exec_result(
        result={
            "sql": "SELECT 1",
            "chart_path": str(chart),
            "dataframe_preview": [],
            "row_count": 0,
            "chart_type": "fancy_3d_unicorn",
        }
    )
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is False
    assert any(e.rule == "chart_type_unknown" for e in out.errors)


# ─── 005-agent-schema-context: zero-row guardrail ────────────────────


def test_empty_result_is_valid_with_reason(tmp_path: Path) -> None:
    """A clean run that returns zero rows is `valid=True` with
    `reason="empty_result"`. The graph maps this to terminal_status
    `succeeded_empty`, not a failure."""
    chart = _make_chart(tmp_path)
    er = _exec_result(
        result={
            "sql": "SELECT * FROM release_fact WHERE style = 'Polka'",
            "chart_path": str(chart),
            "dataframe_preview": [],
            "row_count": 0,
            "chart_type": "line",
        }
    )
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is True
    assert out.errors == []
    assert out.reason == "empty_result"
    assert out.row_count == 0


def test_non_empty_result_has_no_reason(tmp_path: Path) -> None:
    chart = _make_chart(tmp_path)
    er = _exec_result(
        result={
            "sql": "SELECT 1",
            "chart_path": str(chart),
            "dataframe_preview": [{"x": 1}],
            "row_count": 1,
            "chart_type": "bar",
        }
    )
    with use_node("chart_validator"):
        out = chart_validator(
            ValidatorInput(
                execution_result=er,
                expected_chart_dir=str(tmp_path),
            )
        )
    assert out.valid is True
    assert out.reason is None


def test_chart_validator_node_maps_empty_to_succeeded_empty(tmp_path: Path) -> None:
    """The node sets terminal_status='succeeded_empty' and clears
    should_retry when the tool reports empty_result."""
    from discogs_agent.config import settings
    from discogs_agent.graph.nodes.chart_validator import (
        chart_validator_node,
        validation_edge,
    )

    settings.ARTIFACTS_DIR = str(tmp_path)
    chart_dir = tmp_path / "thread-x" / "run-y"
    chart_dir.mkdir(parents=True)
    chart = chart_dir / "chart.html"
    chart.write_text("<html></html>")

    state = {
        "thread_id": "thread-x",
        "run_id": "run-y",
        "execution_result": {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 100,
            "result": {
                "sql": "SELECT * FROM release_fact WHERE style = 'Polka'",
                "chart_path": str(chart),
                "dataframe_preview": [],
                "row_count": 0,
                "chart_type": "line",
            },
            "exception_type": None,
            "exception_message": None,
        },
        "retry_count": 0,
        "max_retries": 2,
    }

    new_state = chart_validator_node(state)  # type: ignore[arg-type]
    assert new_state["terminal_status"] == "succeeded_empty"
    assert new_state["validation_result"]["should_retry"] is False
    assert new_state["validation_result"]["reason"] == "empty_result"

    # Edge must route to the synthesizer, never back to code_generator.
    next_node = validation_edge(new_state)  # type: ignore[arg-type]
    assert next_node == "response_synthesizer"
