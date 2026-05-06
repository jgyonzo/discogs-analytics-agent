"""Path: every code attempt fails → controlled failure response."""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module

_QUERY = "Trigger retries exhausted"


def test_retries_exhausted_failed_safety(agent_env: dict) -> None:
    qhash = stub_module._hash_query(_QUERY)

    bad_code = """import duckdb
import os
con = duckdb.connect(os.environ["ANALYTICS_DUCKDB_PATH"], read_only=True)
sql = "SELECT * FROM stg_releases"
df = con.execute(sql).df()
"""

    original_invoke = stub_module.StubChatModel.invoke

    def patched_invoke(self, messages):
        from discogs_agent.observability.tracing import node_context

        if node_context.get() == "code_generator":
            return stub_module._StubResponse(
                content=bad_code,
                usage={"prompt_tokens": 10, "completion_tokens": 10},
            )
        return original_invoke(self, messages)

    stub_module.StubChatModel.invoke = patched_invoke

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

    assert resp.status == "failed_safety"
    assert resp.chart_artifact is None
    # No traceback in the user response.
    assert "Traceback" not in resp.response
    assert "stg_releases" not in resp.response  # don't leak forbidden table names
