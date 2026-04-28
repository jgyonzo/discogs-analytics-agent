"""Compile the LangGraph StateGraph for the agent.

Eight nodes wired per `contracts/graph.md §1`. Two retry edges from
sql_safety_checker / chart_validator back to code_generator.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from discogs_agent.graph.nodes.chart_validator import (
    chart_validator_node,
    validation_edge,
)
from discogs_agent.graph.nodes.code_generator import code_generator_node
from discogs_agent.graph.nodes.load_schema import load_schema_node
from discogs_agent.graph.nodes.query_understanding import query_understanding_node
from discogs_agent.graph.nodes.response_synthesizer import response_synthesizer_node
from discogs_agent.graph.nodes.router import router_edge, router_node
from discogs_agent.graph.nodes.sandbox_executor import sandbox_executor_node
from discogs_agent.graph.nodes.sql_safety_checker import (
    safety_edge,
    sql_safety_checker_node,
)
from discogs_agent.graph.state import AgentState


def build_graph() -> Any:
    """Compile and return the StateGraph runnable."""
    g = StateGraph(AgentState)

    g.add_node("load_schema", load_schema_node)
    g.add_node("router", router_node)
    g.add_node("query_understanding", query_understanding_node)
    g.add_node("code_generator", code_generator_node)
    g.add_node("sql_safety_checker", sql_safety_checker_node)
    g.add_node("sandbox_executor", sandbox_executor_node)
    g.add_node("chart_validator", chart_validator_node)
    g.add_node("response_synthesizer", response_synthesizer_node)

    # Topology.
    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "router")

    g.add_conditional_edges(
        "router",
        router_edge,
        {
            "query_understanding": "query_understanding",
            "response_synthesizer": "response_synthesizer",
        },
    )
    g.add_edge("query_understanding", "code_generator")
    g.add_edge("code_generator", "sql_safety_checker")

    g.add_conditional_edges(
        "sql_safety_checker",
        safety_edge,
        {
            "sandbox_executor": "sandbox_executor",
            "code_generator": "code_generator",
            "response_synthesizer": "response_synthesizer",
        },
    )
    g.add_edge("sandbox_executor", "chart_validator")

    g.add_conditional_edges(
        "chart_validator",
        validation_edge,
        {
            "code_generator": "code_generator",
            "response_synthesizer": "response_synthesizer",
        },
    )

    g.add_edge("response_synthesizer", END)

    return g.compile()
