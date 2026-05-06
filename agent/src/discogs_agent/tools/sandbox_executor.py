"""Tool: sandbox_executor.

Wraps `sandbox.runner.run_in_sandbox` with the @traced_tool persistence
shim.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.config import settings
from discogs_agent.sandbox.runner import run_in_sandbox
from discogs_agent.tools.base import traced_tool


class SandboxInput(BaseModel):
    generated_code: str
    thread_id: str
    run_id: str
    timeout_seconds: int = 30


class SandboxOutput(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    result: dict[str, Any] | None
    exception_type: str | None
    exception_message: str | None


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[SandboxInput], SandboxOutput]:
    @traced_tool("sandbox_executor", session_provider=session_provider)
    def sandbox_executor(payload: SandboxInput) -> SandboxOutput:
        outcome = run_in_sandbox(
            generated_code=payload.generated_code,
            thread_id=payload.thread_id,
            run_id=payload.run_id,
            timeout_seconds=payload.timeout_seconds,
            duckdb_path=settings.ANALYTICS_DUCKDB_PATH,
            artifacts_root=settings.ARTIFACTS_DIR,
        )
        return SandboxOutput(
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_ms=outcome.duration_ms,
            result=outcome.result,
            exception_type=outcome.exception_type,
            exception_message=outcome.exception_message,
        )

    return sandbox_executor


sandbox_executor = _build()


def make_sandbox_executor(
    session_provider: Callable[[], Session | None],
) -> Callable[[SandboxInput], SandboxOutput]:
    return _build(session_provider)
