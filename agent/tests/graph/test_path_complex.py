"""Path: complex → succeeded.

The stub's diversity/outlier/stylistic queries are routed `complex`
and use the strong-tier model.
"""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module


def test_complex_path(agent_env: dict) -> None:
    # Pre-register a working SQL string for the diversity query so the
    # stub's code_generator branch produces a valid chart.
    stub_module.set_responses(
        {
            (
                "router",
                stub_module._hash_query("Which labels have the most stylistic diversity?"),
            ): '{"complexity": "complex", "selected_model": "gpt-4o", "rationale": "Joins required."}',
            (
                "query_understanding",
                stub_module._hash_query("Which labels have the most stylistic diversity?"),
            ): """{"analysis_intent": "top_n",
             "tables": ["release_label_bridge", "release_fact"],
             "dimensions": ["label_name"],
             "metrics": [
                 {"name": "distinct_styles", "aggregation": "count_distinct", "column": "style"},
                 {"name": "releases", "aggregation": "count_distinct", "column": "release_id"}
             ],
             "filters": [],
             "chart_type": "bar",
             "notes": "join via release_id"}""",
            (
                "code_generator",
                stub_module._hash_query("Which labels have the most stylistic diversity?"),
            ): '''import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path
import os

DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]
ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(DB_PATH, read_only=True)
sql = """
SELECT l.label_name,
       COUNT(DISTINCT f.style) AS distinct_styles,
       COUNT(DISTINCT f.release_id) AS releases
FROM release_label_bridge l
JOIN release_fact f ON l.release_id = f.release_id
GROUP BY l.label_name
ORDER BY distinct_styles DESC
"""
df = con.execute(sql).df()
fig = px.bar(df, x="label_name", y="distinct_styles", title="Label diversity")
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")
RESULT = {"sql": sql, "chart_path": str(chart_path), "dataframe_preview": df.head(20).to_dict(orient="records"), "row_count": len(df), "chart_type": "bar"}
''',
        }
    )

    resp = agent_env["post_query"](
        agent_env["QueryRequest"](message="Which labels have the most stylistic diversity?")
    )
    assert resp.status == "succeeded"
    assert resp.route.complexity == "complex"
    assert resp.route.selected_model == "gpt-4o"
    assert resp.chart_artifact is not None
