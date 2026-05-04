"""Golden suite for feature 005-agent-schema-context, US2.

Asserts that "evolution / over time / trend" questions prefer
`decade` granularity, while explicit yearly intent ("year",
"yearly", "annual") routes to `year`. Anchors SC-005.

The agent's stub LLM consults the query text to pick the grain;
in production the same outcome relies on the decade-preference
hint baked into the schema-context's domain glossary. Both
paths are exercised here through the full graph.
"""

from __future__ import annotations

import pytest

# (question, expected_grain). 15 trend questions → expect decade;
# 5 yearly-intent questions → expect year.
_QUESTIONS: tuple[tuple[str, str], ...] = (
    # Trend — implicit, expect decade.
    ("Show the evolution of Techno releases over time", "decade"),
    ("How have House releases changed over time?", "decade"),
    ("Trend of Ambient releases over time", "decade"),
    ("Drum n Bass releases history", "decade"),
    ("Trance releases evolution", "decade"),
    ("Dub releases over time", "decade"),
    ("Show me Garage release trends", "decade"),
    ("Disco releases history", "decade"),
    ("Show the evolution of Acid Jazz over time", "decade"),
    ("Funk releases over time", "decade"),
    ("Techno trend", "decade"),
    ("How have releases evolved", "decade"),
    ("Trend of releases", "decade"),
    ("Releases history", "decade"),
    ("Releases over time", "decade"),
    # Explicit yearly intent — expect year.
    ("Techno releases year by year", "year"),
    ("House releases yearly", "year"),
    ("Annual Ambient releases", "year"),
    ("Trance releases by year since 2000", "year"),
    ("Show the yearly count of Funk releases", "year"),
)


@pytest.mark.parametrize("question,expected_grain", _QUESTIONS)
def test_question_picks_expected_grain(
    agent_env: dict, question: str, expected_grain: str
) -> None:
    resp = agent_env["post_query"](
        agent_env["QueryRequest"](message=question),
    )
    assert resp.sql is not None, f"no SQL for {question!r}"
    sql_lower = resp.sql.lower()
    other_grain = "year" if expected_grain == "decade" else "decade"
    assert expected_grain in sql_lower, (
        f"{question!r}: expected SQL to use {expected_grain!r}, got: {resp.sql!r}"
    )
    # The non-target grain must not be the GROUP BY dimension.
    assert f"group by {other_grain}" not in sql_lower, (
        f"{question!r}: SQL grouped by {other_grain!r} when {expected_grain!r} "
        f"was expected. SQL: {resp.sql!r}"
    )


def test_decade_preference_passes_threshold(agent_env: dict) -> None:
    """SC-005: ≥18/20 questions match the expected grain."""
    matches = 0
    for question, expected_grain in _QUESTIONS:
        resp = agent_env["post_query"](
            agent_env["QueryRequest"](message=question),
        )
        if resp.sql and expected_grain in resp.sql.lower():
            matches += 1
    assert matches >= 18, (
        f"Decade-preference threshold not met: {matches}/{len(_QUESTIONS)} "
        "(SC-005 requires ≥18/20)."
    )
