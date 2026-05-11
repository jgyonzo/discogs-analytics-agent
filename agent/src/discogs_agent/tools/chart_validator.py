"""Tool: chart_validator.

Applies the validation checklist from `contracts/graph.md §2.7` to a
SandboxOutput-shaped dict.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.tools.base import traced_tool

_ACCEPTED_CHART_TYPES = {
    "bar",
    "line",
    "scatter",
    "pie",
    "histogram",
    "box",
    "area",
    "table",
}


class ValidationError(BaseModel):
    rule: str
    detail: str


class ValidatorInput(BaseModel):
    execution_result: dict[str, Any]
    expected_chart_dir: str


class ValidatorOutput(BaseModel):
    valid: bool
    errors: list[ValidationError] = []
    chart_path: str | None = None
    chart_bytes: int | None = None
    chart_type: str | None = None
    row_count: int | None = None
    # 005-agent-schema-context: a clean run that returns zero rows is
    # `valid=True` but flagged with `reason="empty_result"`. The
    # chart_validator_node maps this to terminal_status="succeeded_empty"
    # without retrying.
    reason: str | None = None


def _validate(payload: ValidatorInput) -> ValidatorOutput:
    errors: list[ValidationError] = []
    er = payload.execution_result

    # 013 / FR-002: when the runner identifies a kernel OOM-kill,
    # short-circuit the legacy three-error layering (`nonzero_exit`
    # + `exception_raised` + `result_missing`) with a single named
    # rule. The OOM cause subsumes the three downstream symptoms;
    # they don't add information for the operator. See
    # specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md.
    if er.get("exception_type") == "oom_killed":
        return ValidatorOutput(
            valid=False,
            errors=[
                ValidationError(
                    rule="oom_killed",
                    detail=str(
                        er.get("exception_message")
                        or "sandbox SIGKILL'd by cgroup OOM-killer"
                    ),
                )
            ],
        )

    if er.get("exit_code") != 0:
        errors.append(
            ValidationError(
                rule="nonzero_exit",
                detail=f"exit_code={er.get('exit_code')}",
            )
        )
    if er.get("exception_type"):
        errors.append(
            ValidationError(
                rule="exception_raised",
                detail=str(er.get("exception_type")),
            )
        )

    result = er.get("result")
    if not isinstance(result, dict):
        errors.append(ValidationError(rule="result_missing", detail="RESULT not present"))
        return ValidatorOutput(valid=False, errors=errors)

    chart_path_str = result.get("chart_path")
    if not isinstance(chart_path_str, str):
        errors.append(ValidationError(rule="chart_path_missing", detail="not a string"))
        return ValidatorOutput(valid=False, errors=errors, row_count=result.get("row_count"))

    chart_path = Path(chart_path_str)
    expected_dir = Path(payload.expected_chart_dir).resolve()
    try:
        chart_resolved = chart_path.resolve()
    except OSError:
        errors.append(ValidationError(rule="chart_path_resolve", detail=chart_path_str))
        return ValidatorOutput(valid=False, errors=errors, chart_path=chart_path_str)

    try:
        chart_resolved.relative_to(expected_dir)
    except ValueError:
        errors.append(
            ValidationError(
                rule="chart_path_outside_dir",
                detail=f"{chart_resolved} not under {expected_dir}",
            )
        )

    if not chart_path.exists():
        errors.append(ValidationError(rule="chart_path_missing_file", detail=str(chart_path)))
    elif chart_path.suffix.lower() != ".html":
        errors.append(ValidationError(rule="chart_extension", detail=chart_path.suffix))

    chart_bytes = chart_path.stat().st_size if chart_path.exists() else None

    preview = result.get("dataframe_preview")
    if not isinstance(preview, list):
        errors.append(ValidationError(rule="preview_not_list", detail=str(type(preview))))

    row_count = result.get("row_count")
    if not isinstance(row_count, int):
        errors.append(ValidationError(rule="row_count_type", detail=str(type(row_count))))

    chart_type = result.get("chart_type")
    if chart_type and chart_type not in _ACCEPTED_CHART_TYPES:
        errors.append(ValidationError(rule="chart_type_unknown", detail=str(chart_type)))

    valid = not errors
    reason: str | None = None
    if valid and isinstance(row_count, int) and row_count == 0:
        reason = "empty_result"

    return ValidatorOutput(
        valid=valid,
        errors=errors,
        chart_path=str(chart_path) if chart_path.exists() else None,
        chart_bytes=chart_bytes,
        chart_type=chart_type if isinstance(chart_type, str) else None,
        row_count=row_count if isinstance(row_count, int) else None,
        reason=reason,
    )


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[ValidatorInput], ValidatorOutput]:
    @traced_tool("chart_validator", session_provider=session_provider)
    def chart_validator(payload: ValidatorInput) -> ValidatorOutput:
        return _validate(payload)

    return chart_validator


chart_validator = _build()


def make_chart_validator(
    session_provider: Callable[[], Session | None],
) -> Callable[[ValidatorInput], ValidatorOutput]:
    return _build(session_provider)
