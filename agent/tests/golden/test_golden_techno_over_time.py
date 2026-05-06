"""Phase 7 / T102 — golden: "Show the evolution of Techno releases over time".

Anchored on docs/discogs_agent_initial_spec.md §20.2. SC-008
anchor: the persisted SQL MUST contain ``COUNT(DISTINCT
release_id)`` OR query ``release_unique_view`` exclusively. The
release-grain count rule is the load-bearing invariant — a naive
``SELECT COUNT(*) FROM release_fact`` over-counts because
release_fact is exploded by style.
"""

from __future__ import annotations


def test_golden_techno_over_time(agent_env: dict) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](message="Show the evolution of Techno releases over time")
    )

    assert resp.status == "succeeded", f"status={resp.status} sql={resp.sql!r}"
    assert resp.row_count > 0
    assert resp.chart_artifact is not None
    assert resp.chart_artifact.type == "plotly_html"

    sql = resp.sql or ""
    sql_lower = sql.lower()

    assert "techno" in sql_lower

    # SC-008: exactly one of the two release-grain disciplines must hold.
    uses_distinct = "count(distinct release_id)" in sql_lower
    uses_unique_view_only = "release_unique_view" in sql_lower and "release_fact" not in sql_lower
    assert uses_distinct or uses_unique_view_only, (
        "SC-008 violation: SQL must use COUNT(DISTINCT release_id) over "
        f"release_fact OR query release_unique_view exclusively. SQL: {sql!r}"
    )
