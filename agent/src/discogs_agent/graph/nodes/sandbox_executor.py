"""Node: sandbox_executor.

Runs the validated code in the restricted subprocess; persists artifact
metadata if a chart was produced.
"""

from __future__ import annotations

from discogs_agent.config import settings
from discogs_agent.graph.state import AgentState
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.artifact_store import ArtifactInput, artifact_store
from discogs_agent.tools.sandbox_executor import SandboxInput, sandbox_executor


def sandbox_executor_node(state: AgentState) -> AgentState:
    with use_node("sandbox_executor"):
        result = sandbox_executor(
            SandboxInput(
                generated_code=state.get("generated_code") or "",
                thread_id=state["thread_id"],
                run_id=state["run_id"],
                timeout_seconds=int(settings.SANDBOX_TIMEOUT_SECONDS),
            )
        )

    state["execution_result"] = result.model_dump()
    state.setdefault("artifact_paths", [])
    state.setdefault("dataframe_preview", [])

    if result.result is not None:
        chart_path = result.result.get("chart_path")
        if isinstance(chart_path, str):
            state["artifact_paths"] = [chart_path]
            preview = result.result.get("dataframe_preview")
            if isinstance(preview, list):
                state["dataframe_preview"] = preview

            # Persist artifact metadata only if validator hasn't yet
            # rejected — but here we pre-record. The validator may
            # invalidate the run; that's OK because the artifact row
            # is still useful for the trace.
            try:
                with use_node("sandbox_executor"):
                    artifact_store(
                        ArtifactInput(
                            run_id=state["run_id"],
                            thread_id=state["thread_id"],
                            artifact_type="plotly_html",
                            path=chart_path,
                            metadata={
                                "chart_type": result.result.get("chart_type"),
                                "row_count": result.result.get("row_count"),
                            },
                        )
                    )
            except ValueError:
                # Path-traversal — handled by validator marking invalid.
                pass

    return state
