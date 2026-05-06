"""US1 acceptance scenario 2: complex analytical question (joins +
COUNT(DISTINCT) + top-N)."""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module


def test_label_diversity_query_succeeds(agent_env: dict) -> None:
    qhash = stub_module._hash_query("Which labels have the most stylistic diversity?")
    stub_module.set_responses(
        {
            (
                "router",
                qhash,
            ): '{"complexity": "complex", "selected_model": "gpt-4o", "rationale": "Joins required."}',
            (
                "query_understanding",
                qhash,
            ): '{"analysis_intent": "top_n", "tables": ["release_label_bridge", "release_fact"], '
            '"dimensions": ["label_name"], "metrics": [{"name": "distinct_styles", "aggregation": "count_distinct", "column": "style"}], '
            '"filters": [], "chart_type": "bar", "notes": ""}',
            ("code_generator", qhash): '''import duckdb
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
       COUNT(DISTINCT f.style)      AS distinct_styles,
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
    # SQL joins both tables and uses COUNT(DISTINCT).
    assert "release_label_bridge" in (resp.sql or "")
    assert "release_fact" in (resp.sql or "")
    assert "COUNT(DISTINCT" in (resp.sql or "").upper()
    assert resp.chart_artifact is not None
