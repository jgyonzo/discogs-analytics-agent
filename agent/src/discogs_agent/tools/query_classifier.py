"""Tool: query_classifier.

Wraps the cheap-tier LLM call with the router prompt to produce a
structured complexity classification.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from discogs_agent.config import settings
from discogs_agent.llm.client import get_chat_client
from discogs_agent.llm.parse import parse_json_response
from discogs_agent.tools.base import traced_tool

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "router.md"


class ClassifierInput(BaseModel):
    user_query: str
    schema_context: dict[str, object]


class ClassifierOutput(BaseModel):
    complexity: Literal["simple", "complex", "unsupported", "clarification_needed"]
    selected_model: str | None
    rationale: str


def _render_prompt(payload: ClassifierInput) -> list[dict[str, str]]:
    """Split the rendered prompt into (system, user) so the stub can
    pattern-match the actual user query — not boilerplate that may
    happen to contain example phrases like "best labels"."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    schema_block = payload.schema_context.get("rendered_block") or ""
    # Stub-out the user_query slot in the system body so the template
    # still renders cleanly; the real user query goes in the user msg.
    system_body = template.format(
        schema_context_block=schema_block,
        cheap_model=settings.CHEAP_MODEL,
        strong_model=settings.STRONG_MODEL,
        user_query="(see user message below)",
    )
    return [
        {"role": "system", "content": system_body},
        {"role": "user", "content": payload.user_query},
    ]


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[ClassifierInput], ClassifierOutput]:
    @traced_tool("query_classifier", session_provider=session_provider)
    def query_classifier(payload: ClassifierInput) -> ClassifierOutput:
        client = get_chat_client(settings.CHEAP_MODEL)
        messages = _render_prompt(payload)
        response = client.invoke(messages)

        try:
            data = parse_json_response(response.content)
            return ClassifierOutput.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            # Defensive fallback: classify as unsupported with the
            # exception message in rationale (truncated). The router
            # node will route this through the unsupported terminal
            # path rather than crashing.
            return ClassifierOutput(
                complexity="unsupported",
                selected_model=None,
                rationale=f"router output unparseable: {type(exc).__name__}",
            )

    return query_classifier


query_classifier = _build()


def make_query_classifier(
    session_provider: Callable[[], Session | None],
) -> Callable[[ClassifierInput], ClassifierOutput]:
    return _build(session_provider)
