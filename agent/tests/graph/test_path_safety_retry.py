"""Path: safety check rejects 1st attempt, repair succeeds on 2nd."""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module

_QUERY = "Trigger safety retry"


def test_safety_retry_then_success(agent_env: dict) -> None:
    qhash = stub_module._hash_query(_QUERY)

    # 1st code-gen → forbidden table reference (will be blocked).
    bad_code = """import duckdb
import os
con = duckdb.connect(os.environ["ANALYTICS_DUCKDB_PATH"], read_only=True)
sql = "SELECT * FROM stg_releases"
df = con.execute(sql).df()
"""
    good_code = """import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path
import os
DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]
ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(DB_PATH, read_only=True)
sql = "SELECT decade, COUNT(*) AS releases FROM release_unique_view GROUP BY decade ORDER BY decade"
df = con.execute(sql).df()
fig = px.bar(df, x="decade", y="releases", title="t")
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")
RESULT = {"sql": sql, "chart_path": str(chart_path), "dataframe_preview": df.head(20).to_dict(orient="records"), "row_count": len(df), "chart_type": "bar"}
"""

    # The stub returns the same content for repeated calls keyed on
    # (node, query_hash). To return different responses across retries,
    # we use a side-effect counter.
    call_count = {"n": 0}

    original_invoke = stub_module.StubChatModel.invoke

    def patched_invoke(self, messages):
        from discogs_agent.observability.tracing import node_context

        node = node_context.get()
        if node == "code_generator":
            call_count["n"] += 1
            content = bad_code if call_count["n"] == 1 else good_code
            return stub_module._StubResponse(
                content=content,
                usage={"prompt_tokens": 10, "completion_tokens": 10},
            )
        return original_invoke(self, messages)

    # Monkeypatch.
    stub_module.StubChatModel.invoke = patched_invoke

    # Pre-register router/query_understanding for our query.
    stub_module.set_responses(
        {
            (
                "router",
                qhash,
            ): '{"complexity": "simple", "selected_model": "gpt-4o-mini", "rationale": "stub"}',
            ("query_understanding", qhash): stub_module._PLAN_BY_DECADE,
        }
    )

    try:
        resp = agent_env["post_query"](agent_env["QueryRequest"](message=_QUERY))
    finally:
        stub_module.StubChatModel.invoke = original_invoke

    assert resp.status == "succeeded", f"got status={resp.status}, response={resp.response!r}"
    assert resp.chart_artifact is not None
    # Two code generations occurred (1 reject, 1 repair).
    assert call_count["n"] >= 2
