"""Per-node tracing context. Used by the @traced_tool decorator to attribute
tool calls to the graph node currently executing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

# Set by every node entry; read by tools/base.py to populate
# agent_tool_calls.node_name. Defaults to "unknown" so unattributed
# calls are still recorded rather than silently dropping FK constraints.
node_context: ContextVar[str] = ContextVar("node_context", default="unknown")

# The active run_id for persistence shim attribution. Set by the API
# layer when invoking the graph; read by tools/base.py.
run_context: ContextVar[str] = ContextVar("run_context", default="")


@contextmanager
def use_node(node_name: str) -> Iterator[None]:
    """Bind `node_name` for the duration of a node's body."""
    token = node_context.set(node_name)
    try:
        yield
    finally:
        node_context.reset(token)


@contextmanager
def use_run(run_id: str) -> Iterator[None]:
    """Bind `run_id` for the duration of a /query call."""
    token = run_context.set(run_id)
    try:
        yield
    finally:
        run_context.reset(token)


def now_ms() -> float:
    """Monotonic time in milliseconds — for latency_ms calculations."""
    return monotonic() * 1000.0
