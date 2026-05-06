"""Phase 7 / T104 — golden: "Which labels have the most stylistic diversity?".

Anchored on docs/discogs_agent_initial_spec.md §20.4. The
canonical SQL joins ``release_label_bridge`` and ``release_fact``
with ``COUNT(DISTINCT)`` aggregates over both ``style`` and
``release_id``.
"""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module
from tests.golden._helpers import wrap_sandbox_code

_QUERY = "Which labels have the most stylistic diversity?"

# Note: the spec's HAVING clause uses ``>= 10``. The seed fixture
# has only a handful of releases per label, so we lower the
# threshold to ``>= 1`` for the test seed. The structural shape
# (the JOIN, the COUNT(DISTINCT) pair) — which is what the SC-008
# anchor cares about — is preserved.
_CANONICAL_SQL = """
SELECT
  l.label_name,
  COUNT(DISTINCT f.style) AS distinct_styles,
  COUNT(DISTINCT f.release_id) AS releases
FROM release_label_bridge l
JOIN release_fact f ON l.release_id = f.release_id
WHERE l.label_name IS NOT NULL AND f.style IS NOT NULL
GROUP BY l.label_name
HAVING COUNT(DISTINCT f.release_id) >= 1
ORDER BY distinct_styles DESC, releases DESC
LIMIT 20
""".strip()

_PLAN = """{
  "analysis_intent": "top_n",
  "tables": ["release_label_bridge", "release_fact"],
  "dimensions": ["label_name"],
  "metrics": [
    {"name": "distinct_styles", "aggregation": "count_distinct", "column": "style"},
    {"name": "releases", "aggregation": "count_distinct", "column": "release_id"}
  ],
  "filters": [],
  "chart_type": "bar",
  "notes": "Join release_label_bridge to release_fact, count distinct styles per label."
}"""


def test_golden_label_diversity(agent_env: dict) -> None:
    qhash = stub_module._hash_query(_QUERY)
    stub_module.set_responses(
        {
            ("query_understanding", qhash): _PLAN,
            ("code_generator", qhash): wrap_sandbox_code(
                _CANONICAL_SQL,
                chart_type="bar",
                plotly_call=(
                    'px.bar(df, x="label_name", y="distinct_styles", '
                    'title="Label stylistic diversity")'
                ),
            ),
        }
    )

    resp = agent_env["post_query"](agent_env["QueryRequest"](message=_QUERY))

    assert resp.status in {"succeeded", "succeeded_empty"}, f"status={resp.status} sql={resp.sql!r}"

    sql_lower = (resp.sql or "").lower()
    assert "release_label_bridge" in sql_lower
    assert "release_fact" in sql_lower
    assert "join" in sql_lower
    assert "count(distinct f.style)" in sql_lower
    assert "count(distinct f.release_id)" in sql_lower
