"""Node: sql_safety_checker.

Wraps the sql_safety_checker tool and routes by the result.
"""

from __future__ import annotations

from discogs_agent.graph.state import AgentState
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.sql_safety_checker import (
    SafetyInput,
)
from discogs_agent.tools.sql_safety_checker import (
    sql_safety_checker as sql_safety_checker_tool,
)


def sql_safety_checker_node(state: AgentState) -> AgentState:
    with use_node("sql_safety_checker"):
        result = sql_safety_checker_tool(
            SafetyInput(
                generated_code=state.get("generated_code") or "",
                schema_context=state["schema_context"],
            )
        )
    state["safety_result"] = result.model_dump()
    state["generated_sql"] = result.extracted_sql
    return state


def safety_edge(state: AgentState) -> str:
    """Returns the next node name."""
    safety = state.get("safety_result") or {}
    if safety.get("allowed"):
        return "sandbox_executor"
    if int(state.get("retry_count", 0)) < int(state.get("max_retries", 2)):
        return "code_generator"
    state["terminal_status"] = "failed_safety"
    return "response_synthesizer"
