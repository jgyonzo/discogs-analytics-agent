"""US4 / T098 — unit tests for build_carryover_preamble.

Pure-function coverage: empty input, single turn within budget,
many turns trimmed from oldest end, and the "produced preamble
never exceeds budget" invariant.
"""

from __future__ import annotations

import tiktoken

from discogs_agent.graph.nodes._carryover import (
    PriorTurn,
    build_carryover_preamble,
)

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _ntokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def test_empty_prior_runs_returns_none() -> None:
    preamble, count = build_carryover_preamble([], token_budget=512)
    assert preamble is None
    assert count == 0


def test_zero_or_negative_budget_returns_none() -> None:
    turns = [PriorTurn("show techno over time")]
    assert build_carryover_preamble(turns, token_budget=0) == (None, 0)
    assert build_carryover_preamble(turns, token_budget=-1) == (None, 0)


def test_single_turn_within_budget_kept() -> None:
    turns = [PriorTurn("show techno over time")]
    preamble, count = build_carryover_preamble(turns, token_budget=512)
    assert count == 1
    assert preamble is not None
    assert "show techno over time" in preamble


def test_budget_too_small_for_any_turn_returns_none() -> None:
    # 5-token budget can't fit even the formatting boilerplate.
    turns = [PriorTurn("show techno over time")]
    preamble, count = build_carryover_preamble(turns, token_budget=5)
    assert preamble is None
    assert count == 0


def test_oldest_dropped_when_budget_exceeded() -> None:
    """Five long turns at ~30 tokens each; budget fits roughly two."""
    long_text = "tell me about the historical evolution of every release"
    turns = [PriorTurn(f"{long_text} ({i})") for i in range(5)]
    # Budget tight enough to fit only the most recent couple of turns.
    preamble, count = build_carryover_preamble(turns, token_budget=60)

    assert preamble is not None
    assert 0 < count < 5

    # The kept turns must be the most recent — i.e. the highest-numbered.
    # The dropped ones (lowest indices) must be absent from the preamble.
    for kept_idx in range(5 - count, 5):
        assert f"({kept_idx})" in preamble
    for dropped_idx in range(0, 5 - count):
        assert f"({dropped_idx})" not in preamble


def test_preamble_never_exceeds_budget() -> None:
    """Whatever build_carryover_preamble returns must fit the budget."""
    turns = [PriorTurn(f"prior question number {i} about Discogs") for i in range(20)]

    for budget in (32, 64, 128, 256, 512):
        preamble, count = build_carryover_preamble(turns, token_budget=budget)
        if preamble is None:
            assert count == 0
            continue
        assert _ntokens(preamble) <= budget, (
            f"preamble {_ntokens(preamble)} tokens > budget {budget}"
        )
        assert count >= 1


def test_chronological_order_preserved() -> None:
    turns = [
        PriorTurn("first question"),
        PriorTurn("second question"),
        PriorTurn("third question"),
    ]
    preamble, count = build_carryover_preamble(turns, token_budget=512)
    assert count == 3
    assert preamble is not None
    pos1 = preamble.index("first question")
    pos2 = preamble.index("second question")
    pos3 = preamble.index("third question")
    assert pos1 < pos2 < pos3
