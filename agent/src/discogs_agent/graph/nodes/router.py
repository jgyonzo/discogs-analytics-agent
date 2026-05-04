"""Node: router.

Calls the query_classifier tool, then logs the cost via cost_logger.
"""

from __future__ import annotations

from discogs_agent.config import settings
from discogs_agent.graph.state import AgentState
from discogs_agent.observability.tracing import now_ms, use_node
from discogs_agent.tools.cost_logger import CostInput, cost_logger
from discogs_agent.tools.query_classifier import ClassifierInput, query_classifier


def router_node(state: AgentState) -> AgentState:
    with use_node("router"):
        start = now_ms()
        result = query_classifier(
            ClassifierInput(
                user_query=state["user_query"],
                schema_context=state["schema_context"],
            )
        )
        latency = int(now_ms() - start)
        cost_logger(
            CostInput(
                node_name="router",
                model_name=settings.CHEAP_MODEL,
                prompt_tokens=0,  # actual usage flows in via the model_usage trace
                completion_tokens=0,
                latency_ms=latency,
            )
        )

    state["route"] = result.model_dump()
    return state


def router_edge(state: AgentState) -> str:
    """Returns the next node name. Either query_understanding or
    response_synthesizer (terminal for unsupported / clarification)."""
    route = state.get("route") or {}
    complexity = route.get("complexity")
    if complexity in ("unsupported", "clarification_needed"):
        return "response_synthesizer"
    return "query_understanding"
