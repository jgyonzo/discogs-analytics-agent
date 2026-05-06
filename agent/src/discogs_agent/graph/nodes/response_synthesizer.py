"""Node: response_synthesizer.

Branches on route + validation/safety state to produce the final
user-facing reply. NEVER includes raw tracebacks.
"""

from __future__ import annotations

import json
from pathlib import Path

from discogs_agent.config import settings
from discogs_agent.graph.state import AgentState
from discogs_agent.llm.client import get_chat_client
from discogs_agent.observability.tracing import now_ms, use_node
from discogs_agent.tools.cost_logger import CostInput, cost_logger

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "response_synthesizer.md"


def response_synthesizer_node(state: AgentState) -> AgentState:
    route = state.get("route") or {}
    complexity = route.get("complexity") or "succeeded"

    # Determine the terminal status. Edge-function mutations don't
    # always propagate in LangGraph, so derive the status here from
    # the visible state:
    #   - unsupported / clarification_needed: from route.
    #   - safety_result.allowed False AND retry_count >= max_retries:
    #     failed_safety.
    #   - validation_result present and not valid: failed_validation.
    #   - validation_result present and valid: succeeded.
    status = state.get("terminal_status")
    if status is None:
        if complexity == "unsupported":
            status = "failed_unsupported"
        elif complexity == "clarification_needed":
            status = "failed_clarification_needed"
        else:
            validation = state.get("validation_result") or {}
            safety = state.get("safety_result") or {}
            if validation.get("valid") and validation.get("reason") == "empty_result":
                status = "succeeded_empty"
            elif validation.get("valid"):
                status = "succeeded"
            elif validation:
                # Validator ran and rejected — and the retry budget
                # has been exhausted (otherwise we'd have looped).
                status = "failed_validation"
            elif safety and not safety.get("allowed"):
                # Safety blocked and the retry budget has been
                # exhausted (no validation_result was ever produced).
                status = "failed_safety"
            else:
                status = "failed_internal"
    state["terminal_status"] = status

    result_block = _build_result_block(state)
    template = PROMPT_PATH.read_text(encoding="utf-8")
    system_body = template.format(
        user_query="(see user message below)",
        complexity=complexity,
        status=status,
        result_block=result_block,
    )
    messages = [
        {"role": "system", "content": system_body},
        {"role": "user", "content": state["user_query"]},
    ]

    with use_node("response_synthesizer"):
        client = get_chat_client(settings.CHEAP_MODEL)
        start = now_ms()
        response = client.invoke(messages)
        latency = int(now_ms() - start)
        cost_logger(
            CostInput(
                node_name="response_synthesizer",
                model_name=settings.CHEAP_MODEL,
                prompt_tokens=int(response.usage.get("prompt_tokens", 0)),
                completion_tokens=int(response.usage.get("completion_tokens", 0)),
                latency_ms=latency,
            )
        )

    final = response.content.strip()
    final = _strip_traceback_artifacts(final)
    state["final_response"] = final
    return state


def _build_result_block(state: AgentState) -> str:
    parts: list[str] = []
    sql = state.get("generated_sql")
    if sql:
        parts.append(f"SQL:\n{sql}")
    validation = state.get("validation_result") or {}
    is_empty = (
        state.get("terminal_status") == "succeeded_empty"
        or validation.get("reason") == "empty_result"
    )
    if is_empty:
        parts.append(
            "Result: no matching releases. The query ran successfully but returned zero rows."
        )
        parts.append(
            "Diagnostic hint: if you were filtering by a musical style "
            "(Techno, House, Ambient, etc.), check whether the value is a "
            "`style` (on release_fact) or a `primary_genre` (on "
            "release_unique_view). The schema context's sample values "
            "show which column carries which kind of value."
        )
    elif validation.get("valid"):
        artifact_paths = state.get("artifact_paths") or []
        if artifact_paths:
            parts.append(f"Chart artifact: {artifact_paths[0]}")
        preview = state.get("dataframe_preview") or []
        if preview:
            parts.append(f"Preview rows ({len(preview)}): {json.dumps(preview[:3])}")
    rationale = (state.get("route") or {}).get("rationale")
    if rationale:
        parts.append(f"Route rationale: {rationale}")
    return "\n\n".join(parts) if parts else "(no result)"


def _strip_traceback_artifacts(text: str) -> str:
    """Belt-and-braces guard: strip lines that look like Python tracebacks.

    The prompt forbids them; this ensures even if the model leaks one,
    it doesn't reach the user.
    """
    bad_markers = ("Traceback (most recent call last)", '  File "', "OPENAI_API_KEY")
    cleaned = []
    for line in text.splitlines():
        if any(marker in line for marker in bad_markers):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip() or "I couldn't produce a response."
