"""Phase 7 / T103 — golden: "Compare Vinyl and CD releases by decade".

Anchored on docs/discogs_agent_initial_spec.md §20.3. The
canonical SQL uses ``has_vinyl`` / ``has_cd`` flags from
``release_unique_view`` and unions per-format aggregates.
"""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module
from tests.golden._helpers import wrap_sandbox_code

_QUERY = "Compare Vinyl and CD releases by decade."

_CANONICAL_SQL = """
SELECT decade, 'Vinyl' AS format, COUNT(*) AS releases
FROM release_unique_view
WHERE has_vinyl = TRUE AND decade IS NOT NULL
GROUP BY decade
UNION ALL
SELECT decade, 'CD' AS format, COUNT(*) AS releases
FROM release_unique_view
WHERE has_cd = TRUE AND decade IS NOT NULL
GROUP BY decade
ORDER BY decade, format
""".strip()

_PLAN = """{
  "analysis_intent": "comparison",
  "tables": ["release_unique_view"],
  "dimensions": ["decade", "format"],
  "metrics": [{"name": "releases", "aggregation": "count", "column": "*"}],
  "filters": [
    {"column": "has_vinyl", "operator": "=", "value": "TRUE"},
    {"column": "has_cd", "operator": "=", "value": "TRUE"}
  ],
  "chart_type": "bar",
  "notes": "UNION ALL on has_vinyl / has_cd against release_unique_view."
}"""


def test_golden_vinyl_vs_cd_by_decade(agent_env: dict) -> None:
    qhash = stub_module._hash_query(_QUERY)
    stub_module.set_responses(
        {
            ("query_understanding", qhash): _PLAN,
            ("code_generator", qhash): wrap_sandbox_code(
                _CANONICAL_SQL,
                chart_type="bar",
                plotly_call=(
                    'px.bar(df, x="decade", y="releases", color="format", '
                    'barmode="group", title="Vinyl vs CD by decade")'
                ),
            ),
        }
    )

    resp = agent_env["post_query"](agent_env["QueryRequest"](message=_QUERY))

    # Some seed shapes have very few CD-only or vinyl-only rows; the run
    # must still finalize cleanly. Both succeeded and succeeded_empty
    # are acceptable terminal states for this golden.
    assert resp.status in {"succeeded", "succeeded_empty"}, f"status={resp.status} sql={resp.sql!r}"

    sql_lower = (resp.sql or "").lower()
    assert "release_unique_view" in sql_lower
    assert "has_vinyl" in sql_lower
    assert "has_cd" in sql_lower
    assert "decade" in sql_lower
