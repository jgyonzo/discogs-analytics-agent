"""LangGraph state TypedDict — the in-flight per-request state."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """The state struct that flows through the graph.

    Field ownership is documented in
    `specs/004-agent-v1/data-model.md §2.1`. `total=False` so nodes
    can populate fields incrementally without listing every key in
    every return.
    """

    # Identity (set by the API before invoke).
    thread_id: str
    run_id: str
    user_query: str

    # Carry-over (set by query_understanding before LLM call).
    carryover_preamble: str | None
    carryover_turn_count: int

    # Schema (set by load_schema).
    schema_context: dict[str, Any]

    # Routing (set by router).
    route: dict[str, Any] | None

    # Plan (set by query_understanding).
    query_plan: dict[str, Any] | None

    # Generation (set by code_generator).
    generated_code: str | None
    generated_sql: str | None

    # Validation outputs.
    safety_result: dict[str, Any] | None
    execution_result: dict[str, Any] | None
    validation_result: dict[str, Any] | None

    # Artifacts.
    artifact_paths: list[str]
    dataframe_preview: list[dict[str, Any]]

    # Retry control.
    retry_count: int
    max_retries: int

    # Trace accumulators (mirrored to Postgres via the persistence shim).
    errors: list[dict[str, Any]]
    model_usage: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]

    # Final.
    final_response: str | None
    terminal_status: str | None  # one of agent_runs.status terminal values
