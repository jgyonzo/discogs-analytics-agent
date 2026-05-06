"""Tool: cost_logger.

Records an LLM invocation in agent_model_usage and returns the new
usage_id + estimated cost.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.llm.pricing import RATE_CARD_VERSION, estimate_cost
from discogs_agent.observability import logging as obslog
from discogs_agent.observability.tracing import run_context
from discogs_agent.persistence.db import current_session
from discogs_agent.persistence.repositories import ModelUsageRepo
from discogs_agent.tools.base import traced_tool

logger = obslog.get_logger(__name__)


class CostInput(BaseModel):
    node_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class CostOutput(BaseModel):
    usage_id: str
    estimated_cost_usd: float | None
    rate_card_version: str


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[CostInput], CostOutput]:
    @traced_tool("cost_logger", session_provider=session_provider)
    def cost_logger(payload: CostInput) -> CostOutput:
        cost: Decimal | None = estimate_cost(
            payload.model_name, payload.prompt_tokens, payload.completion_tokens
        )
        if cost is None:
            logger.warning(
                "unknown_model_for_pricing",
                model_name=payload.model_name,
            )

        usage_id_str = ""
        session = (session_provider or current_session)()
        run_id_str = run_context.get()
        if session is not None and run_id_str:
            repo = ModelUsageRepo(session)
            row = repo.create(
                run_id=UUID(run_id_str),
                node_name=payload.node_name,
                model_name=payload.model_name,
                prompt_tokens=payload.prompt_tokens,
                completion_tokens=payload.completion_tokens,
                estimated_cost_usd=cost,
                latency_ms=payload.latency_ms,
            )
            usage_id_str = str(row.usage_id)

        return CostOutput(
            usage_id=usage_id_str,
            estimated_cost_usd=float(cost) if cost is not None else None,
            rate_card_version=RATE_CARD_VERSION if cost is not None else "unknown",
        )

    return cost_logger


cost_logger = _build()


def make_cost_logger(
    session_provider: Callable[[], Session | None],
) -> Callable[[CostInput], CostOutput]:
    return _build(session_provider)
