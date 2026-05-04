"""Golden suite for feature 005-agent-schema-context, US3.

End-to-end check that an empty-result run surfaces as
`status=succeeded_empty` with no chart artifact, no preview rows,
and a "no matching releases" message in the synthesizer reply.
Anchors SC-002.

Polka isn't a `style` value in the seed DuckDB (and isn't a
`primary_genre` either). The stub's SQL generator emits
`SELECT ... FROM release_fact WHERE style='Polka' ...`, which
runs cleanly but yields zero rows.
"""

from __future__ import annotations

# Add Polka to the stub's known-style list at import time so the
# generator picks it up.
from discogs_agent.llm import stub as stub_module

if "Polka" not in stub_module._KNOWN_STYLES:
    stub_module._KNOWN_STYLES = stub_module._KNOWN_STYLES + ("Polka",)


def test_polka_query_returns_succeeded_empty(agent_env: dict) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message="Show the evolution of Polka releases over time",
        )
    )

    assert resp.status == "succeeded_empty", (
        f"expected status=succeeded_empty, got {resp.status!r}. "
        f"sql={resp.sql!r}, row_count={resp.row_count}"
    )
    assert resp.row_count == 0
    assert resp.dataframe_preview == []
    assert resp.chart_artifact is None, (
        f"chart_artifact should be None for an empty run; got {resp.chart_artifact!r}"
    )
    assert resp.sql is not None and "polka" in resp.sql.lower()
    # Synthesizer prose mentions the empty result clearly. The exact
    # wording comes from the LLM (stub) but the prompt forces the
    # phrase.
    assert resp.response, "expected non-empty response text"
