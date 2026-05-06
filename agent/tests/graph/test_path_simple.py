"""Path: simple → succeeded."""

from __future__ import annotations

from uuid import UUID

from discogs_agent.persistence.db import get_session_factory
from discogs_agent.persistence.repositories import ToolCallRepo


def test_simple_path(agent_env: dict) -> None:
    resp = agent_env["post_query"](agent_env["QueryRequest"](message="Show releases by decade."))
    assert resp.status == "succeeded"
    assert resp.route.complexity == "simple"
    assert resp.sql is not None
    assert resp.chart_artifact is not None
    assert resp.row_count > 0

    # All seven tool types invoked ⇒ SC-006.
    factory = get_session_factory()
    session = factory()
    try:
        tcs = ToolCallRepo(session).list_by_run(UUID(resp.run_id))
        distinct_tools = {tc.tool_name for tc in tcs}
        assert len(distinct_tools) >= 5
    finally:
        session.close()
