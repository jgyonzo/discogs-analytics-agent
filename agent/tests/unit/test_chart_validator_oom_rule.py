"""Unit tests for the chart_validator OOM-named-rule branch (013 / FR-002).

When the sandbox runner identifies a kernel OOM-kill (FR-001) and labels
the outcome ``exception_type="oom_killed"``, the validator MUST emit
exactly ONE ``ValidationError(rule="oom_killed", ...)`` instead of the
legacy three-rule layering (``nonzero_exit`` + ``exception_raised`` +
``result_missing``) that pre-013 produced for every SIGKILL path.

Other ``exception_type`` values keep the legacy layering — the OOM
short-circuit specializes only the OOM case.
"""

from __future__ import annotations

from discogs_agent.tools.chart_validator import (
    ValidatorInput,
    _validate,
)


def _make_input(execution_result: dict) -> ValidatorInput:
    return ValidatorInput(
        execution_result=execution_result,
        expected_chart_dir="/tmp/not-used-on-oom-path",
    )


def test_oom_killed_produces_single_named_rule() -> None:
    """exception_type=="oom_killed" → exactly ONE error with rule="oom_killed".

    Legacy nonzero_exit + exception_raised + result_missing rules
    do NOT fire on this path; they are subsumed by the named cause.
    """
    payload = _make_input(
        {
            "exit_code": -9,
            "exception_type": "oom_killed",
            "exception_message": "kernel SIGKILL (cgroup OOM-killer); "
            "exit_code=-9; sandbox exceeded memory budget",
            "result": None,
            "stdout": "",
            "stderr": "",
        }
    )
    output = _validate(payload)

    assert output.valid is False
    assert len(output.errors) == 1, (
        f"expected exactly one error, got {len(output.errors)}: "
        f"{[e.rule for e in output.errors]}"
    )
    assert output.errors[0].rule == "oom_killed"
    # The detail MUST carry forward the runner's diagnostic message
    # so the response synthesizer and operators can read it.
    assert "OOM" in output.errors[0].detail or "memory" in output.errors[0].detail.lower()


def test_oom_killed_with_empty_message_uses_fallback_detail() -> None:
    """If the runner forgot to populate exception_message, the validator
    falls back to a generic but still-named detail string."""
    payload = _make_input(
        {
            "exit_code": -9,
            "exception_type": "oom_killed",
            "exception_message": None,
            "result": None,
        }
    )
    output = _validate(payload)

    assert output.valid is False
    assert len(output.errors) == 1
    assert output.errors[0].rule == "oom_killed"
    assert output.errors[0].detail  # non-empty fallback


def test_legacy_nonzero_exit_keeps_three_error_layering() -> None:
    """Regression guard: when exception_type is NOT "oom_killed",
    the validator still emits the legacy three-rule layering for
    failure cases (nonzero_exit + exception_raised + result_missing).
    The OOM short-circuit must not regress generic-failure observability."""
    payload = _make_input(
        {
            "exit_code": 1,
            "exception_type": "nonzero_exit",
            "exception_message": "exit_code=1",
            "result": None,
            "stdout": "",
            "stderr": "boom",
        }
    )
    output = _validate(payload)

    assert output.valid is False
    rules = {e.rule for e in output.errors}
    # Pre-013 behaviour: three rules layered.
    assert "nonzero_exit" in rules
    assert "exception_raised" in rules
    assert "result_missing" in rules
    # Specifically NOT oom_killed.
    assert "oom_killed" not in rules


def test_sandbox_signaled_keeps_legacy_layering() -> None:
    """Non-OOM signal kills (SIGSEGV, SIGABRT, etc.) keep the legacy
    layering. The OOM short-circuit is intentionally narrow."""
    payload = _make_input(
        {
            "exit_code": -11,
            "exception_type": "sandbox_signaled",
            "exception_message": "sandbox killed by signal 11; exit_code=-11",
            "result": None,
            "stdout": "",
            "stderr": "",
        }
    )
    output = _validate(payload)

    assert output.valid is False
    rules = {e.rule for e in output.errors}
    assert "oom_killed" not in rules
    assert "nonzero_exit" in rules
    assert "exception_raised" in rules


def test_clean_success_unaffected_by_oom_branch() -> None:
    """Regression guard: the OOM short-circuit must not interfere with
    the clean-success path."""
    payload = _make_input(
        {
            "exit_code": 0,
            "exception_type": None,
            "result": {
                "chart_path": "/tmp/not-used-on-oom-path/chart.html",
                "row_count": 5,
                "dataframe_preview": [{"x": 1}],
                "chart_type": "bar",
            },
        }
    )
    output = _validate(payload)

    # The chart file doesn't exist, so we expect failure — but the
    # failures should be chart_path_missing_file / etc., NOT oom_killed.
    rules = {e.rule for e in output.errors}
    assert "oom_killed" not in rules
