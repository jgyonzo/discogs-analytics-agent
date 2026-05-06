"""Phase 7 / T107 — SC-006 distinct-tools assertion.

A single successful simple run must exercise ≥ 5 distinct tool
types (7 are expected per contracts/tools.md §5). Gives slack
for controlled-failure paths that may skip artifact_store or
chart_validator.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select


def test_distinct_tools_count_for_simple_golden_run(agent_env: dict) -> None:
    resp = agent_env["post_query"](agent_env["QueryRequest"](message="Show releases by decade."))
    assert resp.status == "succeeded"

    from discogs_agent.persistence.db import get_session_factory
    from discogs_agent.persistence.models import ToolCall

    factory = get_session_factory()
    session = factory()
    try:
        stmt = (
            select(func.count(func.distinct(ToolCall.tool_name)))
            .select_from(ToolCall)
            .where(ToolCall.run_id == UUID(resp.run_id))
        )
        distinct_count = int(session.scalar(stmt) or 0)

        all_tool_names = list(
            session.scalars(select(ToolCall.tool_name).where(ToolCall.run_id == UUID(resp.run_id)))
        )
    finally:
        session.close()

    assert distinct_count >= 5, (
        f"SC-006 violation: only {distinct_count} distinct tools fired in run "
        f"{resp.run_id}. Recorded tool_names: {sorted(set(all_tool_names))}"
    )
