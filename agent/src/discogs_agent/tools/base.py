"""@traced_tool decorator.

Wraps Pydantic-input/Pydantic-output callables to:
  - capture latency_ms,
  - catch exceptions, mark status, re-raise,
  - redact known secrets from input_json,
  - persist to agent_tool_calls,
  - attribute the call to the current node via the tracing ContextVar.

Also defines the per-node allowlist enforcement.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.observability import logging as obslog
from discogs_agent.observability.tracing import node_context, now_ms, run_context
from discogs_agent.persistence.db import current_session
from discogs_agent.persistence.repositories import ToolCallRepo

logger = obslog.get_logger(__name__)


# ─── Node × tool allowlist (from contracts/tools.md §3) ──────────────


NODE_TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
    "load_schema": frozenset({"dataset_schema_reader"}),
    "router": frozenset({"query_classifier", "cost_logger"}),
    "query_understanding": frozenset({"dataset_schema_reader", "cost_logger"}),
    "code_generator": frozenset({"cost_logger"}),
    "sql_safety_checker": frozenset({"sql_safety_checker"}),
    "sandbox_executor": frozenset({"sandbox_executor", "artifact_store"}),
    "chart_validator": frozenset({"chart_validator"}),
    "response_synthesizer": frozenset({"artifact_store", "cost_logger"}),
}


class ToolNotAllowedError(RuntimeError):
    """A node attempted to call a tool not in its allowlist."""


def assert_tool_allowed(node: str, tool: str) -> None:
    allowed = NODE_TOOL_ALLOWLIST.get(node, frozenset())
    if tool not in allowed:
        raise ToolNotAllowedError(
            f"Node {node!r} is not allowed to call tool {tool!r}. Allowed: {sorted(allowed)}"
        )


# ─── Secret-shaped key redaction ─────────────────────────────────────


_SECRET_KEYS = {
    "api_key",
    "openai_api_key",
    "database_url",
    "aws_access_key_id",
    "aws_secret_access_key",
}


def _redact(payload: Any) -> Any:
    """Recursively replace known-secret-shaped values with `***`."""
    if isinstance(payload, dict):
        return {k: ("***" if k.lower() in _SECRET_KEYS else _redact(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_redact(x) for x in payload]
    return payload


# ─── @traced_tool decorator ───────────────────────────────────────────


_T_in = TypeVar("_T_in", bound=BaseModel)
_T_out = TypeVar("_T_out", bound=BaseModel)


def traced_tool(
    tool_name: str,
    *,
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[Callable[[_T_in], _T_out]], Callable[[_T_in], _T_out]]:
    """Decorator factory.

    `session_provider` is a callable returning the current SQLAlchemy
    session for persistence. When None or returning None, persistence
    is skipped (e.g., in pure unit tests that don't supply a session).
    """

    def decorator(fn: Callable[[_T_in], _T_out]) -> Callable[[_T_in], _T_out]:
        @functools.wraps(fn)
        def wrapper(input_model: _T_in) -> _T_out:
            node = node_context.get()
            assert_tool_allowed(node, tool_name)

            input_json = _redact(input_model.model_dump())
            start = now_ms()
            status = "succeeded"
            output: _T_out | None = None
            error_msg: str | None = None

            try:
                output = fn(input_model)
                return output
            except Exception as exc:
                status = "failed"
                error_msg = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                latency_ms = int(now_ms() - start)
                _persist_tool_call(
                    session_provider=session_provider,
                    node=node,
                    tool_name=tool_name,
                    input_json=input_json,
                    output=output,
                    status=status,
                    latency_ms=latency_ms,
                    error_msg=error_msg,
                )

        return wrapper

    return decorator


def _persist_tool_call(
    *,
    session_provider: Callable[[], Session | None] | None,
    node: str,
    tool_name: str,
    input_json: dict[str, Any],
    output: BaseModel | None,
    status: str,
    latency_ms: int,
    error_msg: str | None,
) -> None:
    # Provider chain: explicit provider > request-scoped context-var.
    if session_provider is not None:
        session = session_provider()
    else:
        session = current_session()
    if session is None:
        return
    run_id_str = run_context.get()
    if not run_id_str:
        # No active run — most likely a pure unit test calling a tool
        # outside the request lifecycle. Skip persistence.
        return
    run_id = UUID(run_id_str)

    output_json: dict[str, Any] | None = None
    if output is not None:
        try:
            output_json = _redact(output.model_dump())
        except Exception as exc:  # pragma: no cover — guard-rail
            logger.warning("tool_output_serialization_failed", error=str(exc))
            output_json = None

    repo = ToolCallRepo(session)
    repo.create(
        run_id=run_id,
        node_name=node,
        tool_name=tool_name,
        input_json=input_json,
        output_json=output_json,
        status=status,
        latency_ms=latency_ms,
        error_message=error_msg,
    )
