"""Unit tests for the signal-aware exception_type mapping (013 / FR-001).

Covers the ``_signal_aware_exception`` helper at the catch-all branch of
``sandbox/runner.py``. The canonical taxonomy lives at
``specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md``.

The precedence cases (harness timeout label preserved; Python-side
``_error`` preserved) are exercised by the existing integration tests
``test_sandbox_timeout`` (timeout path) and ``test_sandbox_python_exception``
flavours — they remain green post-013 and serve as the regression guards
for cases 2 and 5 from the taxonomy contract's §Unit-test coverage list.
"""

from __future__ import annotations

from discogs_agent.sandbox.runner import _signal_aware_exception


def test_sigkill_external_yields_oom_killed() -> None:
    """exit_code == -9 + exception_type is None → "oom_killed" with a message
    naming the cgroup OOM-killer."""
    exc_type, exc_msg = _signal_aware_exception(-9)
    assert exc_type == "oom_killed"
    # The message MUST be human-meaningful enough to dashboard on.
    assert "OOM" in exc_msg or "memory" in exc_msg.lower()
    assert "-9" in exc_msg


def test_other_negative_exit_yields_sandbox_signaled() -> None:
    """Any negative exit code other than -9 maps to "sandbox_signaled"
    with the signal number preserved in the message."""
    # SIGSEGV.
    exc_type, exc_msg = _signal_aware_exception(-11)
    assert exc_type == "sandbox_signaled"
    assert "signal 11" in exc_msg
    assert "exit_code=-11" in exc_msg


def test_sigterm_yields_sandbox_signaled() -> None:
    """SIGTERM (-15) is grouped under the same umbrella as other non-OOM signals."""
    exc_type, exc_msg = _signal_aware_exception(-15)
    assert exc_type == "sandbox_signaled"
    assert "signal 15" in exc_msg


def test_positive_nonzero_exit_yields_nonzero_exit() -> None:
    """A clean Python-side ``sys.exit(n)`` keeps the legacy ``nonzero_exit``
    label — the post-013 catch-all preserves backward compatibility for
    positive non-zero exits."""
    exc_type, exc_msg = _signal_aware_exception(1)
    assert exc_type == "nonzero_exit"
    assert exc_msg == "exit_code=1"


def test_mapping_is_deterministic() -> None:
    """FR-005: the helper is a pure function of its input. Same input,
    same output, on every call."""
    for code in (-9, -11, -15, 1, 2, 137):
        a = _signal_aware_exception(code)
        b = _signal_aware_exception(code)
        assert a == b, f"non-deterministic mapping for exit_code={code}"


def test_oom_killed_message_contains_canonical_phrase() -> None:
    """The OOM message MUST contain a downstream-greppable phrase so the
    response synthesizer and operators can identify the cause without
    pattern-matching on exit_code."""
    _, exc_msg = _signal_aware_exception(-9)
    assert "cgroup OOM-killer" in exc_msg
