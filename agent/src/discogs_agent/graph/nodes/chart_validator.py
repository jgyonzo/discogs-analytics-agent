"""Node: chart_validator.

Wraps the chart_validator tool and decides retry.
"""

from __future__ import annotations

from pathlib import Path

from discogs_agent.config import settings
from discogs_agent.graph.state import AgentState
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.chart_validator import (
    ValidatorInput,
    chart_validator as chart_validator_tool,
)


def chart_validator_node(state: AgentState) -> AgentState:
    expected_dir = str(
        Path(settings.ARTIFACTS_DIR)
        / state["thread_id"]
        / state["run_id"]
    )
    with use_node("chart_validator"):
        result = chart_validator_tool(
            ValidatorInput(
                execution_result=state.get("execution_result") or {},
                expected_chart_dir=expected_dir,
            )
        )

    out = result.model_dump()
    # 005: a valid run with zero rows is a clean terminal state — no retry.
    if result.valid and result.reason == "empty_result":
        out["should_retry"] = False
        state["validation_result"] = out
        state["terminal_status"] = "succeeded_empty"
        return state

    out["should_retry"] = (not result.valid) and (
        int(state.get("retry_count", 0)) < int(state.get("max_retries", 2))
    )
    state["validation_result"] = out
    return state


def validation_edge(state: AgentState) -> str:
    """Returns the next node name."""
    if state.get("terminal_status") == "succeeded_empty":
        return "response_synthesizer"
    validation = state.get("validation_result") or {}
    if validation.get("valid"):
        return "response_synthesizer"
    if validation.get("should_retry"):
        return "code_generator"
    state["terminal_status"] = "failed_validation"
    return "response_synthesizer"
