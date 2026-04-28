"""Node: code_generator.

Selects the code_generator prompt on first entry and the repair prompt
on retry. Increments retry_count.
"""

from __future__ import annotations

import json
from pathlib import Path

from discogs_agent.config import settings
from discogs_agent.graph.state import AgentState
from discogs_agent.llm.client import get_chat_client
from discogs_agent.observability.tracing import now_ms, use_node
from discogs_agent.tools.cost_logger import CostInput, cost_logger

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _summarize_schema(schema_context: dict) -> str:
    tables = schema_context.get("tables", {})
    if not isinstance(tables, dict):
        return "(none)"
    lines = []
    for tbl, cols in tables.items():
        col_list = ", ".join(c["name"] if isinstance(c, dict) else c.name for c in cols)
        lines.append(f"- {tbl}: {col_list}")
    return "\n".join(lines) if lines else "(none)"


def _strip_code_fence(text: str) -> str:
    """LLMs sometimes wrap code in ```python … ```. Strip if present."""
    t = text.strip()
    if t.startswith("```"):
        # Drop opening fence line.
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Drop closing fence.
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t


def code_generator_node(state: AgentState) -> AgentState:
    schema_context = state["schema_context"]
    plan = state.get("query_plan") or {}
    retry_count = int(state.get("retry_count", 0))
    route = state.get("route") or {}
    selected_model = route.get("selected_model") or settings.CHEAP_MODEL

    if retry_count == 0:
        template = (PROMPTS_DIR / "code_generator.md").read_text(encoding="utf-8")
        system_body = template.format(
            tables_summary=_summarize_schema(schema_context),
            has_master_fact=str(bool(schema_context.get("has_master_fact"))).lower(),
            query_plan=json.dumps(plan, indent=2),
            user_query="(see user message below)",
        )
    else:
        # Repair prompt — surface the failure details.
        failure_details = "\n".join(
            _format_failures(state)
        ) or "(no specific failure recorded)"
        template = (PROMPTS_DIR / "repair_code.md").read_text(encoding="utf-8")
        system_body = template.format(
            tables_summary=_summarize_schema(schema_context),
            query_plan=json.dumps(plan, indent=2),
            previous_code=state.get("generated_code") or "",
            previous_sql=state.get("generated_sql") or "",
            failure_details=failure_details,
            user_query="(see user message below)",
        )

    messages = [
        {"role": "system", "content": system_body},
        {"role": "user", "content": state["user_query"]},
    ]

    with use_node("code_generator"):
        client = get_chat_client(selected_model)
        start = now_ms()
        response = client.invoke(messages)
        latency = int(now_ms() - start)

        cost_logger(
            CostInput(
                node_name="code_generator",
                model_name=selected_model,
                prompt_tokens=int(response.usage.get("prompt_tokens", 0)),
                completion_tokens=int(response.usage.get("completion_tokens", 0)),
                latency_ms=latency,
            )
        )

    state["generated_code"] = _strip_code_fence(response.content)
    state["retry_count"] = retry_count + 1
    return state


def _format_failures(state: AgentState) -> list[str]:
    parts: list[str] = []
    safety = state.get("safety_result")
    if isinstance(safety, dict) and safety.get("violations"):
        parts.append("Safety violations:")
        for v in safety["violations"]:
            parts.append(f"  - {v.get('rule')}: {v.get('detail')}")
    validation = state.get("validation_result")
    if isinstance(validation, dict) and validation.get("errors"):
        parts.append("Validation errors:")
        for v in validation["errors"]:
            parts.append(f"  - {v.get('rule')}: {v.get('detail')}")
    execution = state.get("execution_result")
    if isinstance(execution, dict):
        if execution.get("exception_type"):
            parts.append(f"Sandbox exception: {execution['exception_type']}: {execution.get('exception_message', '')}")
    return parts
