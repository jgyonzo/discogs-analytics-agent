"""US3 / T092 — GET /threads/{id} basic shape.

Three runs under one thread; assert run_count=3, runs in
chronological order, and each successful run's primary_artifact
has a populated url.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_threads_endpoint_lists_runs_with_primary_artifact(
    agent_env: dict,
) -> None:
    from discogs_agent.api import app

    QR = agent_env["QueryRequest"]
    post = agent_env["post_query"]

    r1 = post(QR(message="Show the evolution of Techno releases over time"))
    assert r1.status == "succeeded"
    thread_id = r1.thread_id

    r2 = post(QR(message="Show the evolution of Techno releases over time", thread_id=thread_id))
    r3 = post(QR(message="Show the evolution of Techno releases over time", thread_id=thread_id))

    with TestClient(app) as client:
        resp = client.get(f"/threads/{thread_id}")

    assert resp.status_code == 200
    body = resp.json()

    assert body["thread_id"] == thread_id
    assert body["run_count"] == 3
    runs = body["runs"]
    assert [r["run_id"] for r in runs] == [r1.run_id, r2.run_id, r3.run_id]

    for r in runs:
        if r["status"] == "succeeded":
            assert r["primary_artifact"] is not None
            assert r["primary_artifact"]["url"].startswith("/artifacts/")
