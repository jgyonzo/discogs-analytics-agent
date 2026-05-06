"""US3 / T093 — GET /threads/{id} pagination.

Five runs under one thread; assert limit/offset slicing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_threads_endpoint_pagination(agent_env: dict) -> None:
    from discogs_agent.api import app

    QR = agent_env["QueryRequest"]
    post = agent_env["post_query"]

    runs = []
    first = post(QR(message="Show the evolution of Techno releases over time"))
    runs.append(first)
    thread_id = first.thread_id
    for _ in range(4):
        runs.append(
            post(
                QR(
                    message="Show the evolution of Techno releases over time",
                    thread_id=thread_id,
                )
            )
        )

    expected_ids = [r.run_id for r in runs]

    with TestClient(app) as client:
        page1 = client.get(f"/threads/{thread_id}", params={"limit": 2}).json()
        page2 = client.get(f"/threads/{thread_id}", params={"limit": 2, "offset": 2}).json()
        page3 = client.get(f"/threads/{thread_id}", params={"limit": 2, "offset": 4}).json()

    assert page1["run_count"] == 5
    assert [r["run_id"] for r in page1["runs"]] == expected_ids[0:2]
    assert [r["run_id"] for r in page2["runs"]] == expected_ids[2:4]
    assert [r["run_id"] for r in page3["runs"]] == expected_ids[4:5]
