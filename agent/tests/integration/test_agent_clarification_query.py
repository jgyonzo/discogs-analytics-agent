"""US1 acceptance scenario 4: clarification-needed query."""

from __future__ import annotations


def test_best_labels_returns_clarification(agent_env: dict) -> None:
    resp = agent_env["post_query"](agent_env["QueryRequest"](message="Show me the best labels."))
    assert resp.status == "failed_clarification_needed"
    assert resp.route.complexity == "clarification_needed"
    assert resp.sql is None
    assert resp.chart_artifact is None
    assert len(resp.response) > 10
