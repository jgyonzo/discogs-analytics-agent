"""Phase 7 / T101 — golden: "Show releases by decade".

Anchored on docs/discogs_agent_initial_spec.md §20.1. The stub
LLM's default for an unstyled "decade" query already returns the
canonical SQL (`release_unique_view`, COUNT(*) by decade, chart
type bar), so this test exercises the full graph end-to-end and
asserts the persisted SQL + the chart artifact's metadata.
"""

from __future__ import annotations

from uuid import UUID


def test_golden_releases_by_decade(agent_env: dict) -> None:
    resp = agent_env["post_query"](agent_env["QueryRequest"](message="Show releases by decade."))

    assert resp.status == "succeeded", f"status={resp.status} sql={resp.sql!r}"
    assert resp.row_count > 0
    assert resp.chart_artifact is not None
    assert resp.chart_artifact.type == "plotly_html"

    sql_lower = (resp.sql or "").lower()
    assert "release_unique_view" in sql_lower
    assert "release_fact" not in sql_lower, (
        "decade aggregation must use release_unique_view (release-grain), "
        "not release_fact (style-cross-product grain)."
    )
    assert "group by" in sql_lower
    assert "decade" in sql_lower

    # Chart-type assertion lives on the artifact metadata, set by
    # the artifact_store tool from the sandbox RESULT block.
    from discogs_agent.persistence.db import get_session_factory
    from discogs_agent.persistence.repositories import ArtifactRepo

    factory = get_session_factory()
    session = factory()
    try:
        artifacts = ArtifactRepo(session).list_by_run(UUID(resp.run_id))
        assert artifacts, "expected at least one artifact for the run"
        meta = artifacts[0].metadata_json or {}
        assert meta.get("chart_type") == "bar"
    finally:
        session.close()
