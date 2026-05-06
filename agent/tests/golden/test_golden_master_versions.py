"""Phase 7 / T106 — golden: "Which works have the most versions?".

Anchored on docs/discogs_agent_initial_spec.md §20.6. Two
variants:

  * ``with_master_fact`` — runs against ``seed.duckdb``. Stub
    canned SQL queries ``master_fact`` ordered by
    ``release_count``; the run succeeds.
  * ``no_master_fact`` — runs against ``seed_no_master.duckdb``.
    Router stub returns ``unsupported`` because the question
    requires a table that's not present in the published
    snapshot; the run finalizes ``failed_unsupported``.
"""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module
from tests.golden._helpers import wrap_sandbox_code

_QUERY = "Which works have the most versions?"

_CANONICAL_SQL = """
SELECT title, release_count
FROM master_fact
WHERE title IS NOT NULL
ORDER BY release_count DESC
LIMIT 20
""".strip()

_PLAN = """{
  "analysis_intent": "top_n",
  "tables": ["master_fact"],
  "dimensions": ["title"],
  "metrics": [{"name": "release_count", "aggregation": "max", "column": "release_count"}],
  "filters": [],
  "chart_type": "bar",
  "notes": "master_fact is pre-aggregated; just order by release_count."
}"""

_ROUTER_UNSUPPORTED = (
    '{"complexity": "unsupported", "selected_model": null, '
    '"rationale": "Question requires master_fact, which is not present '
    'in this DuckDB snapshot."}'
)


def test_golden_master_versions_with_master_fact(agent_env: dict) -> None:
    qhash = stub_module._hash_query(_QUERY)
    stub_module.set_responses(
        {
            ("query_understanding", qhash): _PLAN,
            ("code_generator", qhash): wrap_sandbox_code(
                _CANONICAL_SQL,
                chart_type="bar",
                plotly_call=(
                    'px.bar(df, x="title", y="release_count", title="Works with the most versions")'
                ),
            ),
        }
    )

    resp = agent_env["post_query"](agent_env["QueryRequest"](message=_QUERY))
    assert resp.status == "succeeded", f"status={resp.status} sql={resp.sql!r}"
    assert resp.row_count > 0
    assert resp.chart_artifact is not None

    sql_lower = (resp.sql or "").lower()
    assert "master_fact" in sql_lower
    assert "release_count" in sql_lower
    assert "order by release_count desc" in sql_lower


def test_golden_master_versions_without_master_fact(
    agent_env_no_master: dict,
) -> None:
    qhash = stub_module._hash_query(_QUERY)
    stub_module.set_responses(
        {
            ("router", qhash): _ROUTER_UNSUPPORTED,
        }
    )

    resp = agent_env_no_master["post_query"](agent_env_no_master["QueryRequest"](message=_QUERY))
    assert resp.status == "failed_unsupported", (
        f"expected failed_unsupported, got status={resp.status} sql={resp.sql!r}"
    )
    assert resp.chart_artifact is None
    assert resp.sql is None
    assert resp.route.complexity == "unsupported"
