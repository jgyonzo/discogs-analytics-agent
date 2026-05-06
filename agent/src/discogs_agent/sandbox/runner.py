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
        exception_type = "nonzero_exit"
        exception_message = f"exit_code={exit_code}"

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
