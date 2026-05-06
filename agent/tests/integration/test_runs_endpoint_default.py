"""US3 / T089 — GET /runs/{id} non-admin shape.

Submits a real successful query through the stub LLM, then reads
the run via the inspection endpoint without admin auth. Asserts
that tool_calls and model_usage are populated, and that
generated_code + errors[].traceback are nulled.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_runs_endpoint_default_shape(agent_env: dict) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="Show the evolution of Techno releases over time",
        )
    )
    assert resp.status == "succeeded"
    run_id = resp.run_id

    from discogs_agent.api import app

    with TestClient(app) as client:
        r = client.get(f"/runs/{run_id}")

    assert r.status_code == 200
    body = r.json()

    assert body["run_id"] == run_id
    assert body["thread_id"] == resp.thread_id
    assert body["status"] == "succeeded"
    assert body["generated_sql"] is not None
    # Non-admin: generated_code is nulled.
    assert body["generated_code"] is None

    assert isinstance(body["tool_calls"], list) and len(body["tool_calls"]) > 0
    assert isinstance(body["model_usage"], list) and len(body["model_usage"]) > 0
    assert isinstance(body["artifacts"], list) and len(body["artifacts"]) > 0

    # Non-admin: any error rows have traceback nulled.
    for err in body["errors"]:
        assert err["traceback"] is None

    md = body["metadata"]
    assert md["retry_count"] >= 0
    # route_rationale comes from router; stub provides it
    assert md["route_rationale"] is not None
