"""Path: unsupported → response_synthesizer (no codegen, no sandbox)."""

from __future__ import annotations

from uuid import UUID

from discogs_agent.persistence.db import get_session_factory
from discogs_agent.persistence.repositories import ToolCallRepo


def test_unsupported_path(agent_env: dict) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="What is the average price of Techno releases?",
        )
    )
    assert resp.status == "failed_unsupported"
    assert resp.route.complexity == "unsupported"
    assert resp.sql is None
    assert resp.chart_artifact is None

    # No sandbox or safety tools should have been invoked.
    factory = get_session_factory()
    session = factory()
    try:
        tcs = ToolCallRepo(session).list_by_run(UUID(resp.run_id))
        tools = {tc.tool_name for tc in tcs}
        assert "sandbox_executor" not in tools
        assert "sql_safety_checker" not in tools
        assert "chart_validator" not in tools
    finally:
        session.close()
