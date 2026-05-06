"""Tests for the cost_logger tool."""

from __future__ import annotations

from discogs_agent.llm.pricing import RATE_CARD_VERSION, estimate_cost
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.cost_logger import CostInput, cost_logger


def test_known_model_returns_cost() -> None:
    cost = estimate_cost("gpt-4o-mini", 1000, 500)
    assert cost is not None
    assert cost > 0


def test_unknown_model_returns_none() -> None:
    assert estimate_cost("gpt-99-nonexistent", 1000, 500) is None


def test_cost_logger_runs_without_session() -> None:
    """When no session_provider is wired, the tool still computes the
    estimate (just doesn't persist)."""
    with use_node("router"):
        out = cost_logger(
            CostInput(
                node_name="router",
                model_name="gpt-4o-mini",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
            )
        )
    assert out.estimated_cost_usd is not None
    assert out.rate_card_version == RATE_CARD_VERSION


def test_cost_logger_unknown_model_warns() -> None:
    with use_node("router"):
        out = cost_logger(
            CostInput(
                node_name="router",
                model_name="gpt-mystery",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
            )
        )
    assert out.estimated_cost_usd is None
    assert out.rate_card_version == "unknown"
