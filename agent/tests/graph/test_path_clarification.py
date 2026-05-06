"""Path: clarification_needed → response_synthesizer (no codegen)."""

from __future__ import annotations


def test_clarification_path(agent_env: dict) -> None:
    resp = agent_env["post_query"](agent_env["QueryRequest"](message="Show me the best labels."))
    assert resp.status == "failed_clarification_needed"
    assert resp.route.complexity == "clarification_needed"
    assert resp.sql is None
    assert resp.chart_artifact is None
