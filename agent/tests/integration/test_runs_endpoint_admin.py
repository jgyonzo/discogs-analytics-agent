"""US3 / T090 — GET /runs/{id} admin shape.

With AGENT_ADMIN_TOKEN set and the matching X-Agent-Admin header,
the response must include generated_code (string) and
errors[].traceback for unexpected-bucket errors. Without the
header, the same endpoint must return the non-admin shape.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient


def test_runs_endpoint_admin_reveals_code_and_traceback(
    agent_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discogs_agent.api import app
    from discogs_agent.config import settings
    from discogs_agent.persistence.db import get_session_factory
    from discogs_agent.persistence.repositories import ErrorRepo

    monkeypatch.setattr(settings, "AGENT_ADMIN_TOKEN", "test-token")

    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="Show the evolution of Techno releases over time",
        )
    )
    assert resp.status == "succeeded"
    run_id = resp.run_id

    # Synthesize an unexpected-bucket error with traceback.
    factory = get_session_factory()
    session = factory()
    try:
        ErrorRepo(session).create(
            run_id=UUID(run_id),
            node_name="api",
            error_type="unexpected",
            error_message="RuntimeError: synthetic",
            traceback=(
                'Traceback (most recent call last):\n'
                '  File "<stdin>", line 1, in <module>\n'
                "RuntimeError: synthetic"
            ),
        )
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        admin_resp = client.get(
            f"/runs/{run_id}",
            headers={"X-Agent-Admin": "test-token"},
        )
        anon_resp = client.get(f"/runs/{run_id}")
        wrong_token_resp = client.get(
            f"/runs/{run_id}",
            headers={"X-Agent-Admin": "wrong-token"},
        )

    # Admin shape: generated_code populated, traceback populated.
    assert admin_resp.status_code == 200
    abody = admin_resp.json()
    assert isinstance(abody["generated_code"], str) and abody["generated_code"]
    err_rows = [e for e in abody["errors"] if e["error_type"] == "unexpected"]
    assert len(err_rows) == 1
    assert err_rows[0]["traceback"] is not None
    assert "Traceback" in err_rows[0]["traceback"]

    # Non-admin shape: nulled.
    for unauth in (anon_resp, wrong_token_resp):
        assert unauth.status_code == 200
        body = unauth.json()
        assert body["generated_code"] is None
        for err in body["errors"]:
            assert err["traceback"] is None


def test_admin_disabled_when_token_empty(
    agent_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default deny: even with the header, an empty AGENT_ADMIN_TOKEN
    must NOT elevate the request."""
    from discogs_agent.api import app
    from discogs_agent.config import settings

    monkeypatch.setattr(settings, "AGENT_ADMIN_TOKEN", "")

    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="Show the evolution of Techno releases over time",
        )
    )
    run_id = resp.run_id

    with TestClient(app) as client:
        r = client.get(
            f"/runs/{run_id}", headers={"X-Agent-Admin": "anything"}
        )

    assert r.status_code == 200
    body = r.json()
    assert body["generated_code"] is None
