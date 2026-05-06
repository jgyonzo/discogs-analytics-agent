"""US1 acceptance scenario 5: safety check exhaustion → controlled
failure (not crash)."""

from __future__ import annotations

import hashlib

from discogs_agent.llm import stub as stub_module


def test_safety_exhaustion_returns_controlled_failure(agent_env: dict) -> None:
    qhash = stub_module._hash_query("force forbidden table on every retry")

    bad_code = """import duckdb
import os
con = duckdb.connect(os.environ["ANALYTICS_DUCKDB_PATH"], read_only=True)
sql = "SELECT * FROM stg_releases"
df = con.execute(sql).df()
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

    # Compute the DuckDB checksum before and after to verify SC-007:
    # no mutation occurred.
    duckdb_path = agent_env["duckdb_path"]
    before = hashlib.sha256(open(duckdb_path, "rb").read()).hexdigest()

    try:
        resp = agent_env["post_query"](
            agent_env["QueryRequest"](message="force forbidden table on every retry")
        )
    finally:
        stub_module.StubChatModel.invoke = original_invoke

    after = hashlib.sha256(open(duckdb_path, "rb").read()).hexdigest()

    assert resp.status == "failed_safety"
    assert resp.chart_artifact is None
    # No traceback in the user-facing response.
    assert "Traceback" not in resp.response
    # Don't leak the forbidden table name to the end-user.
    assert "stg_releases" not in resp.response
    # SC-007 partial: byte-equal before/after.
    assert before == after, "DuckDB was mutated during safety-block run"
