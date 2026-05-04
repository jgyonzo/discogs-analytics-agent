"""Golden suite for feature 005-agent-schema-context, US1.

Drives the full graph (stub LLM backend) for the 10 canonical
musical styles and asserts each returns a non-empty result whose
SQL filters by `style` on `release_fact`. Anchors SC-001 — the
"every style query should produce real data" success criterion.

Pre-fix baseline: 0/10 styles return data because the model
filters `primary_genre = 'Techno'` (etc.) on
`release_unique_view`, where no row matches.
Post-fix: 10/10 styles return data via `WHERE style = '<value>'`
on `release_fact`.
"""

from __future__ import annotations

import pytest

# The 10 canonical styles tracked by SC-001. Match the constants
# in `agent/src/discogs_agent/llm/stub.py:_KNOWN_STYLES` and the
# rows added to `agent/tests/fixtures/seed_duckdb.py`.
_CANONICAL_STYLES = (
    "Techno",
    "House",
    "Ambient",
    "Drum n Bass",
    "Trance",
    "Dub",
    "Garage",
    "Disco",
    "Acid Jazz",
    "Funk",
)


@pytest.mark.parametrize("style", _CANONICAL_STYLES)
def test_canonical_style_returns_non_empty_result(
    agent_env: dict, style: str
) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](
            message=f"Show the evolution of {style} releases over time",
        )
    )

    assert resp.status == "succeeded", (
        f"{style!r}: status was {resp.status!r}, expected 'succeeded'. "
        f"sql={resp.sql!r}"
    )
    assert resp.row_count > 0, (
        f"{style!r}: row_count={resp.row_count}, expected > 0. SQL: {resp.sql!r}"
    )
    assert len(resp.dataframe_preview) > 0, (
        f"{style!r}: dataframe_preview is empty. SQL: {resp.sql!r}"
    )

    sql_lower = (resp.sql or "").lower()
    assert "release_fact" in sql_lower, (
        f"{style!r}: SQL did not query release_fact. SQL: {resp.sql!r}"
    )
    assert f"style = '{style.lower()}'" in sql_lower or f'style="{style}"' in (
        resp.sql or ""
    ), (
        f"{style!r}: SQL did not filter by `style = '{style}'`. SQL: {resp.sql!r}"
    )
    assert f"primary_genre = '{style.lower()}'" not in sql_lower, (
        f"{style!r}: SQL incorrectly filtered by primary_genre. SQL: {resp.sql!r}"
    )


def test_canonical_styles_all_succeed(agent_env: dict) -> None:
    """SC-001 check: 10/10 canonical styles return data."""
    successes = 0
    for style in _CANONICAL_STYLES:
        resp = agent_env["post_query"](
            agent_env["QueryRequest"](
                message=f"Show the evolution of {style} releases over time",
            )
        )
        if resp.status == "succeeded" and resp.row_count > 0:
            successes += 1
    assert successes == len(_CANONICAL_STYLES), (
        f"Only {successes}/{len(_CANONICAL_STYLES)} canonical styles produced "
        "non-empty results."
    )
