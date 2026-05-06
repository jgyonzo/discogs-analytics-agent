"""Verifies the node x tool allowlist matches contracts/tools.md §3."""

from __future__ import annotations

from discogs_agent.tools.base import NODE_TOOL_ALLOWLIST

_EXPECTED: dict[str, set[str]] = {
    "load_schema": {"dataset_schema_reader"},
    "router": {"query_classifier", "cost_logger"},
    "query_understanding": {"dataset_schema_reader", "cost_logger"},
    "code_generator": {"cost_logger"},
    "sql_safety_checker": {"sql_safety_checker"},
    "sandbox_executor": {"sandbox_executor", "artifact_store"},
    "chart_validator": {"chart_validator"},
    "response_synthesizer": {"artifact_store", "cost_logger"},
}


def test_allowlist_matches_contract() -> None:
    actual = {node: set(tools) for node, tools in NODE_TOOL_ALLOWLIST.items()}
    assert actual == _EXPECTED, (
        "Node x tool allowlist drifted from contracts/tools.md §3.\n"
        f"  expected: {_EXPECTED}\n"
        f"  actual:   {actual}"
    )


def test_allowlist_has_eight_nodes() -> None:
    assert len(NODE_TOOL_ALLOWLIST) == 8


def test_distinct_tool_count_at_least_five() -> None:
    """SC-006 requires ≥ 5 distinct tools across the agent's flow."""
    distinct = set().union(*NODE_TOOL_ALLOWLIST.values())
    assert len(distinct) >= 5
    # In V1 we expect exactly 7.
    assert distinct == {
        "dataset_schema_reader",
        "query_classifier",
        "cost_logger",
        "sql_safety_checker",
        "sandbox_executor",
        "chart_validator",
        "artifact_store",
    }
