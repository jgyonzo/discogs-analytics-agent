"""US3 / T094 — GET /runs/{id} 404."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def test_runs_endpoint_404_unknown_uuid(agent_env: dict) -> None:
    from discogs_agent.api import app

    with TestClient(app) as client:
        resp = client.get(f"/runs/{uuid4()}")

    assert resp.status_code == 404
    body = resp.json()
    # Error envelope is wrapped in FastAPI's `detail`.
    assert body["detail"]["error"]["code"] == "run_not_found"


def test_runs_endpoint_404_bad_uuid(agent_env: dict) -> None:
    from discogs_agent.api import app

    with TestClient(app) as client:
        resp = client.get("/runs/not-a-uuid")

    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["error"]["code"] == "run_not_found"
