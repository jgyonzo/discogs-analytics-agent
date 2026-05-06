"""US3 / T091 — GET /runs/{id} secret-leak guard.

After a deliberate sandbox failure (which produces a sandbox-side
traceback), the non-admin response body must not contain
``Traceback (most recent`` or ``OPENAI_API_KEY``. Literal grep over
the serialized JSON.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from discogs_agent.llm import stub as stub_module


def test_runs_endpoint_no_secret_leak_on_sandbox_failure(
    agent_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discogs_agent.api import app
    from discogs_agent.config import settings
    from discogs_agent.persistence.db import get_session_factory
    from discogs_agent.persistence.repositories import ErrorRepo

    # Admin disabled (default) — non-admin path under test.
    monkeypatch.setattr(settings, "AGENT_ADMIN_TOKEN", "")

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
    run_id = resp.run_id

    # Realistic worst case: tracebacks DO get persisted to agent_errors
    # for some failure paths. Seed one to make the leak guard meaningful
    # — even if the real traceback row is empty in this controlled bucket.
    factory = get_session_factory()
    session = factory()
    try:
        ErrorRepo(session).create(
            run_id=UUID(run_id),
            node_name="sandbox",
            error_type="sandbox_exception",
            error_message="RuntimeError: forced failure",
            traceback=(
                "Traceback (most recent call last):\n"
                '  File "/sandbox/generated.py", line 5, in <module>\n'
                "    raise RuntimeError('forced failure')\n"
                "OPENAI_API_KEY=sk-leaky-secret\n"
                "RuntimeError: forced failure"
            ),
        )
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        r = client.get(f"/runs/{run_id}")

    assert r.status_code == 200
    body_text = json.dumps(r.json())
    assert "Traceback (most recent" not in body_text
    assert "OPENAI_API_KEY" not in body_text
