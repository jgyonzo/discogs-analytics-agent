"""US1 acceptance scenario 3: unsupported query → controlled response."""

from __future__ import annotations


def test_price_query_returns_unsupported(agent_env: dict) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](message="What is the average price of Techno releases?")
    )
    assert resp.status == "failed_unsupported"
    assert resp.route.complexity == "unsupported"
    assert resp.sql is None
    assert resp.chart_artifact is None
    # The response must be non-empty and actionable.
    assert len(resp.response) > 10
    # No raw exception leakage.
    assert "Traceback" not in resp.response
