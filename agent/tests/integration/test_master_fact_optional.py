"""US1 acceptance scenario 7: master_fact optional handling.

When the snapshot lacks master_fact, master-only questions classify
as unsupported; release-grain questions still succeed.
"""

from __future__ import annotations

from discogs_agent.llm import stub as stub_module


def test_master_question_unsupported_when_master_absent(
    agent_env_no_master: dict,
) -> None:
    # Simulate what a real LLM, given schema_context.has_master_fact=False,
    # would classify a master-only question as. The stub's fallback
    # doesn't see has_master_fact, so we pre-register the response.
    qhash = stub_module._hash_query("Which works have the most versions?")
    stub_module.set_responses(
        {
            ("router", qhash): '{"complexity": "unsupported", "selected_model": null, '
            '"rationale": "master_fact not present in this snapshot"}',
        }
    )

    resp = agent_env_no_master["post_query"](
        agent_env_no_master["QueryRequest"](message="Which works have the most versions?")
    )
    assert resp.status == "failed_unsupported"
    assert resp.chart_artifact is None


def test_master_query_blocked_at_safety_when_master_absent(
    agent_env_no_master: dict,
) -> None:
    """Belt-and-braces: even if the router lets a master_fact query
    through, the safety check rejects it as forbidden_table."""
    qhash = stub_module._hash_query("force master_fact reference")

    bad_code = """import duckdb
import os
con = duckdb.connect(os.environ["ANALYTICS_DUCKDB_PATH"], read_only=True)
sql = "SELECT title, release_count FROM master_fact ORDER BY release_count DESC"
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

    try:
        resp = agent_env_no_master["post_query"](
            agent_env_no_master["QueryRequest"](message="force master_fact reference")
        )
    finally:
        stub_module.StubChatModel.invoke = original_invoke

    assert resp.status == "failed_safety"
    assert resp.chart_artifact is None


def test_release_query_succeeds_when_master_absent(
    agent_env_no_master: dict,
) -> None:
    resp = agent_env_no_master["post_query"](
        agent_env_no_master["QueryRequest"](
            message="Show releases by decade.",
        )
    )
    assert resp.status == "succeeded"
    assert resp.chart_artifact is not None
