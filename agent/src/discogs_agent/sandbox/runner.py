"""Run user-generated Python in a restricted subprocess.

Returns a `SandboxOutcome` with stdout/stderr/exit_code/result.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from discogs_agent.sandbox.restrictions import clean_env, make_preexec

WRAPPER_PATH = Path(__file__).parent / "wrapper.py.tmpl"

_RESULT_RE = re.compile(
    r"__AGENT_RESULT_BEGIN__(?P<payload>.*?)__AGENT_RESULT_END__",
    re.DOTALL,
)

_OUTPUT_CAP_BYTES = 16 * 1024


def _signal_aware_exception(exit_code: int) -> tuple[str, str]:
    """Map a non-zero exit code to a named exception_type + message.

    Called from the catch-all branch when ``exception_type`` is still
    ``None`` after the harness-timeout path, RESULT parsing, and
    ``_error`` extraction have all declined to set it. The mapping is
    pure (no I/O, no env) and exhaustive over the negative-vs-positive
    space — see ``specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md``
    for the canonical taxonomy.

    Returns:
        (exception_type, exception_message) for the given ``exit_code``.

    Examples:
        >>> _signal_aware_exception(-9)[0]
        'oom_killed'
        >>> _signal_aware_exception(-11)[0]
        'sandbox_signaled'
        >>> _signal_aware_exception(1)[0]
        'nonzero_exit'
    """
    if exit_code == -9:
        return (
            "oom_killed",
            "kernel SIGKILL (cgroup OOM-killer); "
            "exit_code=-9; sandbox exceeded memory budget",
        )
    if exit_code < 0:
        signal_num = -exit_code
        return (
            "sandbox_signaled",
            f"sandbox killed by signal {signal_num}; exit_code={exit_code}",
        )
    return ("nonzero_exit", f"exit_code={exit_code}")


@dataclass
class SandboxOutcome:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    result: dict[str, Any] | None
    exception_type: str | None
    exception_message: str | None


def _truncate(text: str, cap: int = _OUTPUT_CAP_BYTES) -> str:
    if len(text.encode("utf-8")) <= cap:
        return text
    return text[: cap // 2] + "\n…[truncated]\n" + text[-cap // 2 :]


def run_in_sandbox(
    *,
    generated_code: str,
    thread_id: str,
    run_id: str,
    timeout_seconds: int,
    duckdb_path: str,
    artifacts_root: str,
) -> SandboxOutcome:
    """Run `generated_code` in a restricted subprocess.

    Writes the code to a temp .py inside the per-run artifact directory
    and invokes `python -I -B -S wrapper.py <script>`.
    """
    artifact_dir = Path(artifacts_root) / thread_id / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    script_path = artifact_dir / "generated.py"
    script_path.write_text(generated_code, encoding="utf-8")

    env = clean_env(duckdb_path=duckdb_path, artifact_dir=str(artifact_dir))
    preexec = make_preexec(timeout_seconds)

    # `-I` (isolated mode) suppresses PYTHONPATH, user-site, and
    # `usercustomize.py`. Do NOT add `-S` — it would also disable
    # `site.py`, which loads installed packages (duckdb, pandas, plotly).
    cmd = [
        sys.executable,
        "-I",
        "-B",
        str(WRAPPER_PATH),
        str(script_path),
    ]

    started = monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(artifact_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=preexec,
        start_new_session=True,
        text=True,
    )

    exception_type: str | None = None
    exception_message: str | None = None

    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        # Kill the whole process group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()
        stdout, stderr = proc.communicate()
        exit_code = -9
        exception_type = "timeout"
        exception_message = f"sandbox exceeded {timeout_seconds}s wall-clock"

    duration_ms = int((monotonic() - started) * 1000)

    # Parse the RESULT block out of stdout.
    result: dict[str, Any] | None = None
    payload_dict: dict[str, Any] | None = None
    match = _RESULT_RE.search(stdout)
    if match:
        try:
            import json

            payload_dict = json.loads(match.group("payload"))
        except Exception as exc:
            exception_type = exception_type or "parse_failed"
            exception_message = exception_message or f"failed to parse RESULT: {exc}"
            payload_dict = None

    if payload_dict is not None:
        if "_error" in payload_dict:
            exception_type = exception_type or payload_dict.get("_error")
            exception_message = (
                exception_message or payload_dict.get("_message") or payload_dict.get("_traceback")
            )
            result = None
        else:
            result = payload_dict.get("result")

    if exit_code != 0 and exception_type is None:
        # Signal-aware mapping (013): distinguish kernel OOM-kill from
        # other signal kills from positive non-zero exits. The harness's
        # own SIGKILL-on-timeout path sets exception_type="timeout"
        # above (line ~108), so a `-9` reaching here is necessarily
        # external (cgroup OOM-killer in the deployed sandbox).
        exception_type, exception_message = _signal_aware_exception(exit_code)

    if result is None and exception_type is None and exit_code == 0:
        # Subprocess ran clean but emitted no marker — typically means
        # the script never reached the bottom (no RESULT) or the
        # marker was clipped.
        exception_type = "no_result"
        exception_message = "RESULT block not found in subprocess stdout"

    # Strip the RESULT block from the stdout we surface back.
    stdout_clean = _RESULT_RE.sub("", stdout).strip()

    return SandboxOutcome(
        exit_code=exit_code,
        stdout=_truncate(stdout_clean),
        stderr=_truncate(stderr),
        duration_ms=duration_ms,
        result=result,
        exception_type=exception_type,
        exception_message=exception_message,
    )
