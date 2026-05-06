"""Build the multi-turn carry-over preamble (US4 / R-04).

Given the most recent N runs of a thread (chronological, oldest
first), produce a "Recent conversation" preamble that fits inside
the configured token budget. Trim from the oldest end until the
preamble's tiktoken count is within budget.

Carries only the prior `user_query` text — never SQL, generated
code, or final responses. The "no SQL/code carry-over" boundary
is what the spec calls "light contextual carry-over."
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class PriorTurn:
    """Minimal shape of a prior run needed to build the preamble.

    The graph node converts ORM rows to this so the builder can be
    unit-tested without touching the database.
    """

    user_query: str


def _tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _format_turn(idx: int, turn: PriorTurn) -> str:
    return f"  {idx}. {turn.user_query.strip()}"


def _format_preamble(turns: list[PriorTurn]) -> str:
    body = "\n".join(_format_turn(i + 1, t) for i, t in enumerate(turns))
    return f"Recent conversation (prior user questions in this thread, oldest first):\n{body}\n"


def build_carryover_preamble(
    prior_runs: list[PriorTurn],
    token_budget: int,
) -> tuple[str | None, int]:
    """Return (preamble, turn_count).

    `prior_runs` must be ordered oldest-first. The most recent N
    turns are kept; older turns are dropped until the preamble fits
    `token_budget` tokens (cl100k_base). A budget too small to fit
    even the single most recent turn yields ``(None, 0)`` rather
    than truncating mid-query.
    """
    if not prior_runs or token_budget <= 0:
        return (None, 0)

    # Walk newest → oldest. After each step, `kept` holds the
    # most-recent-N turns we've accepted, in chronological order
    # (oldest-first within the kept set). Stop the first time
    # adding the next-older turn would exceed budget — older turns
    # past that are dropped, not the newer ones already kept.
    kept: list[PriorTurn] = []
    for turn in reversed(prior_runs):
        candidate = [turn] + kept
        if _tokens(_format_preamble(candidate)) <= token_budget:
            kept = candidate
        else:
            break

    if not kept:
        return (None, 0)
    return (_format_preamble(kept), len(kept))
