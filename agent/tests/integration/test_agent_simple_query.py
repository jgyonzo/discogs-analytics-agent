"""US1 acceptance scenario 1: simple analytical question + chart.

Anchors SC-008 — the persisted SQL for the Techno-over-time question
must use COUNT(DISTINCT release_id) (or release_unique_view).
"""

from __future__ import annotations


def test_simple_query_returns_chart(agent_env: dict) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="Show the evolution of Techno releases over time",
        )
    )
    assert resp.status == "succeeded"
    assert resp.route.complexity == "simple"
    assert resp.sql is not None
    assert resp.chart_artifact is not None
    assert resp.row_count > 0
    assert len(resp.dataframe_preview) > 0

    # The chart artifact file exists on disk.
    chart_dir = agent_env["artifacts"] / resp.thread_id / resp.run_id
    chart_files = list(chart_dir.glob("*.html"))
    assert chart_files, f"no .html under {chart_dir}"
    assert chart_files[0].stat().st_size > 0


def test_simple_query_uses_count_distinct(agent_env: dict) -> None:
    """SC-008 anchor: the persisted SQL must use COUNT(DISTINCT
    release_id) or query release_unique_view exclusively."""
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="Show the evolution of Techno releases over time",
        )
    )
    assert resp.sql is not None
    sql_lower = resp.sql.lower()
    uses_distinct = "count(distinct release_id)" in sql_lower
    uses_unique_view = "release_unique_view" in sql_lower and "release_fact" not in sql_lower
    assert uses_distinct or uses_unique_view, f"SQL violates count rule: {resp.sql!r}"
