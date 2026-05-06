"""US4 / T099 — multi-turn carry-over.

Submits a Techno query, captures `thread_id`, then submits a
follow-up against the same thread. Asserts:
  (a) the second run's `metadata.carryover.turn_count` is 1
  (b) the carryover preamble contains the first query's text
  (c) the second run succeeds, and the carryover preamble is
      injected into the query_understanding prompt (and only that
      prompt — R-04: router stays stateless). A run on the same
      query *without* the thread_id sees no carryover preamble.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from discogs_agent.llm import stub as stub_module


def test_thread_resume_carries_prior_query_text(agent_env: dict) -> None:
    QR = agent_env["QueryRequest"]
    post = agent_env["post_query"]

    r1 = post(QR(message="Show the evolution of Techno releases over time"))
    assert r1.status == "succeeded"
    thread_id = r1.thread_id

    # Capture the messages each node sees so we can verify carry-over
    # only lands in query_understanding (and only when the thread is
    # being resumed).
    captured: dict[str, list[str]] = {}
    original_invoke = stub_module.StubChatModel.invoke

    def patched(self, messages):
        from discogs_agent.observability.tracing import node_context

        node = node_context.get() or "_unknown"
        captured.setdefault(node, []).append("\n".join(m.get("content", "") for m in messages))
        return original_invoke(self, messages)

    stub_module.StubChatModel.invoke = patched
    try:
        # Follow-up on the same thread.
        r2 = post(
            QR(
                message="Show the evolution of House releases over time",
                thread_id=thread_id,
            )
        )
        # Same query, brand-new thread (no carry-over available).
        r3 = post(QR(message="Show the evolution of House releases over time"))
    finally:
        stub_module.StubChatModel.invoke = original_invoke

    assert r2.status == "succeeded"
    assert r3.status == "succeeded"
    assert r2.thread_id == thread_id
    assert r3.thread_id != thread_id

    # (c) Carry-over preamble lands in query_understanding only on r2.
    qu_prompts = captured.get("query_understanding", [])
    assert len(qu_prompts) == 2
    r2_qu_prompt, r3_qu_prompt = qu_prompts
    assert "Recent conversation" in r2_qu_prompt
    assert "Techno releases over time" in r2_qu_prompt
    assert "Recent conversation" not in r3_qu_prompt

    # Router is stateless — even on the resumed thread, no prior text
    # reaches the router prompt (R-04).
    router_prompts = captured.get("router", [])
    for p in router_prompts:
        assert "Recent conversation" not in p

    # (a) and (b) — verify via the inspection endpoint.
    from discogs_agent.api import app

    with TestClient(app) as client:
        r2_full = client.get(f"/runs/{r2.run_id}").json()
        r3_full = client.get(f"/runs/{r3.run_id}").json()

    r2_carryover = r2_full["metadata"]["carryover"]
    assert r2_carryover is not None
    assert r2_carryover["turn_count"] == 1
    assert "Techno releases over time" in r2_carryover["preamble"]

    # The fresh thread has no carry-over.
    assert r3_full["metadata"]["carryover"] is None
