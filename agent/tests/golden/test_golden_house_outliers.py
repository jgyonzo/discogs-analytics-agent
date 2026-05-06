"""Phase 7 / T105 — golden: "Detect outlier years for House releases".

Anchored on docs/discogs_agent_initial_spec.md §20.5. The
canonical SQL is a CTE-based outlier detector using
``STDDEV_SAMP`` and a z-score filter. The router classifies this
as ``complex`` because it uses CTEs and a derived metric.
"""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module
from tests.golden._helpers import wrap_sandbox_code

_QUERY = "Detect outlier years for House releases."

_CANONICAL_SQL = """
WITH yearly_counts AS (
  SELECT year, COUNT(DISTINCT release_id) AS releases
  FROM release_fact
  WHERE style = 'House' AND year IS NOT NULL
  GROUP BY year
),
stats AS (
  SELECT AVG(releases) AS avg_releases,
         STDDEV_SAMP(releases) AS stddev_releases
  FROM yearly_counts
)
SELECT
  y.year,
  y.releases,
  (y.releases - s.avg_releases) / NULLIF(s.stddev_releases, 0) AS z_score
FROM yearly_counts y
CROSS JOIN stats s
WHERE ABS((y.releases - s.avg_releases) / NULLIF(s.stddev_releases, 0)) >= 2
ORDER BY ABS(z_score) DESC
""".strip()

_PLAN = """{
  "analysis_intent": "outlier",
  "tables": ["release_fact"],
  "dimensions": ["year"],
  "metrics": [
    {"name": "releases", "aggregation": "count_distinct", "column": "release_id"},
    {"name": "z_score", "aggregation": "derived", "column": "(releases - avg) / stddev"}
  ],
  "filters": [{"column": "style", "operator": "=", "value": "House"}],
  "chart_type": "scatter",
  "notes": "Two-stage CTE: yearly counts then stats, z-score filter."
}"""


def test_golden_house_outliers(agent_env: dict) -> None:
    qhash = stub_module._hash_query(_QUERY)
    stub_module.set_responses(
        {
            ("query_understanding", qhash): _PLAN,
            ("code_generator", qhash): wrap_sandbox_code(
                _CANONICAL_SQL,
                chart_type="scatter",
                plotly_call=(
                    'px.scatter(df, x="year", y="z_score", '
                    'size="releases", title="House outlier years")'
                ),
            ),
        }
    )

    resp = agent_env["post_query"](agent_env["QueryRequest"](message=_QUERY))

    # The seed has too few House years for stddev to flag any outliers,
    # so a clean empty result is also acceptable here.
    assert resp.status in {"succeeded", "succeeded_empty"}, f"status={resp.status} sql={resp.sql!r}"

    sql_upper = (resp.sql or "").upper()
    assert "WITH " in sql_upper
    assert "STDDEV_SAMP" in sql_upper
    sql_lower = (resp.sql or "").lower()
    assert "release_fact" in sql_lower
    assert "style = 'house'" in sql_lower
