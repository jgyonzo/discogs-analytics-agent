"""US1 acceptance scenario 6: sandbox raises on every retry →
controlled failure."""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module


def test_sandbox_exhaustion_returns_controlled_failure(agent_env: dict) -> None:
    qhash = stub_module._hash_query("force runtime exception")

    bad_code = """import duckdb
import os
con = duckdb.connect(os.environ["ANALYTICS_DUCKDB_PATH"], read_only=True)
sql = "SELECT decade FROM release_unique_view"
df = con.execute(sql).df()
raise RuntimeError("forced failure")
"""

    original_invoke = stub_module.StubChatModel.invoke

    def patched(self, messages):
        from discogs_agent.observability.tracing import node_context

        if node_context.get() == "code_generator":
            return stub_module._StubResponse(
                content=bad_code, usage={"prompt_tokens": 10, "completion_tokens": 10}
            )
        return original_invoke(self, messages)

    stub_module.StubChatModel.invoke = patched
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
        resp = agent_env["post_query"](agent_env["QueryRequest"](message="force runtime exception"))
    finally:
        stub_module.StubChatModel.invoke = original_invoke

    assert resp.status == "failed_validation"
    assert resp.chart_artifact is None
    # FR-024: no traceback in the user response.
    assert "Traceback" not in resp.response
    assert "forced failure" not in resp.response
