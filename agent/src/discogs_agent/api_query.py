"""Routes for /query and /artifacts.

The /query endpoint orchestrates: thread resolution / creation, run row
creation, building the LangGraph initial state, invoking the graph,
finalizing the run, projecting state to the response DTO.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from discogs_agent.api import app
from discogs_agent.config import settings
from discogs_agent.duckdb_layer.schema import reset_schema_cache
from discogs_agent.graph.builder import build_graph
from discogs_agent.observability import logging as obslog
from discogs_agent.observability.tracing import use_run
from discogs_agent.persistence.db import get_session_factory, use_session
from discogs_agent.persistence.repositories import (
    ArtifactRepo,
    ErrorRepo,
    RunRepo,
    ThreadRepo,
    ToolCallRepo,
)

logger = obslog.get_logger(__name__)


# ─── DTOs ─────────────────────────────────────────────────────────────


class QueryRequest(BaseModel):
    thread_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    debug: bool = False


class RouteSummary(BaseModel):
    complexity: str | None
    selected_model: str | None
    rationale: str | None


class ChartArtifactRef(BaseModel):
    artifact_id: str
    url: str
    type: str = "plotly_html"


class CarryoverInfo(BaseModel):
    turn_count: int
    preamble: str | None


class QueryResponse(BaseModel):
    thread_id: str
    run_id: str
    response: str
    route: RouteSummary
    sql: str | None
    code: str | None
    chart_artifact: ChartArtifactRef | None
    dataframe_preview: list[dict[str, Any]]
    row_count: int
    status: str
    carryover: CarryoverInfo


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorEnvelope(BaseModel):
    error: ErrorPayload


# ─── Helpers ──────────────────────────────────────────────────────────


_GRAPH = None


def _get_graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def _set_graph(graph: Any) -> None:
    """Test-only: inject a precompiled graph (e.g., for path tests)."""
    global _GRAPH
    _GRAPH = graph


def _resolve_thread(session: Session, thread_id: str | None) -> tuple[str, bool]:
    """Returns (thread_id, was_created)."""
    repo = ThreadRepo(session)
    if thread_id is not None:
        try:
            uuid_obj = UUID(thread_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "invalid_request", "message": f"bad thread_id: {exc}"}},
            ) from exc
        thread = repo.get(uuid_obj)
        if thread is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "thread_not_found", "message": str(thread_id)}},
            )
        return str(thread.thread_id), False
    new = repo.create()
    return str(new.thread_id), True


# ─── /query ───────────────────────────────────────────────────────────


@app.post("/query", response_model=QueryResponse)
def post_query(payload: QueryRequest) -> QueryResponse:
    """Run one analytical question through the LangGraph."""
    factory = get_session_factory()
    session = factory()

    try:
        thread_id, _created = _resolve_thread(session, payload.thread_id)
        run_repo = RunRepo(session)
        run = run_repo.create(UUID(thread_id), payload.message)
        run_id = str(run.run_id)
        session.commit()
    except HTTPException:
        session.close()
        raise
    except Exception as exc:
        session.rollback()
        session.close()
        logger.exception("query_setup_failed")
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "internal_error", "message": str(exc)}},
        ) from exc

    started_at = datetime.now(timezone.utc)

    initial_state = {
        "thread_id": thread_id,
        "run_id": run_id,
        "user_query": payload.message,
        "retry_count": 0,
        "max_retries": int(settings.MAX_RETRIES),
        "errors": [],
        "model_usage": [],
        "tool_calls": [],
        "artifact_paths": [],
        "dataframe_preview": [],
    }

    final_state: dict | None = None
    error_obj: Exception | None = None
    try:
        # Bind both the run_id and the session for the request scope.
        # @traced_tool reads both from contextvars, so all tool calls
        # invoked within this block persist to the same session.
        with use_run(run_id), use_session(session):
            graph = _get_graph()
            final_state = graph.invoke(initial_state)
    except Exception as exc:
        error_obj = exc
        logger.exception("graph_invoke_failed", run_id=run_id)
        # Record an unexpected error.
        try:
            ErrorRepo(session).create(
                run_id=UUID(run_id),
                node_name="api",
                error_type="unexpected",
                error_message=f"{type(exc).__name__}: {exc}",
                traceback=None,
            )
            session.commit()
        except Exception:
            session.rollback()

    finished_at = datetime.now(timezone.utc)
    latency_ms = int((finished_at - started_at).total_seconds() * 1000)

    if error_obj is not None or final_state is None:
        # Internal failure path.
        run_repo.finalize(
            run_id=UUID(run_id),
            status="failed_internal",
            final_response=(
                "Something unexpected went wrong. The error is logged "
                f"with run_id {run_id}."
            ),
            latency_ms=latency_ms,
        )
        session.commit()
        session.close()
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "internal_error", "message": "internal_error", "details": {"run_id": run_id}}},
        )

    # Project final state into the response.
    route = final_state.get("route") or {}
    status = final_state.get("terminal_status") or "succeeded"

    # Persist into agent_runs.
    if route:
        run_repo.update_route(
            run_id=UUID(run_id),
            complexity=route.get("complexity") or "unsupported",
            selected_model=route.get("selected_model"),
        )
    sql = final_state.get("generated_sql")
    if sql:
        run_repo.update_generated_sql(UUID(run_id), sql)

    # Carry-over (US4 — empty in MVP).
    carryover_preamble = final_state.get("carryover_preamble")
    carryover_turn_count = int(final_state.get("carryover_turn_count", 0))
    if carryover_preamble or carryover_turn_count:
        run_repo.update_metadata(
            UUID(run_id),
            carryover={
                "turn_count": carryover_turn_count,
                "preamble": carryover_preamble,
            },
        )

    final_text = final_state.get("final_response") or ""
    run_repo.finalize(
        run_id=UUID(run_id),
        status=status,
        final_response=final_text,
        latency_ms=latency_ms,
    )

    # Pull the primary chart artifact (if any). For empty-result runs,
    # suppress the artifact reference: the chart file may exist on
    # disk (the sandbox produced it before validation) but it's blank
    # and shipping it confuses the user.
    chart_ref: ChartArtifactRef | None = None
    if status != "succeeded_empty":
        artifacts = ArtifactRepo(session).list_by_run(UUID(run_id))
        if artifacts:
            a = artifacts[0]
            chart_ref = ChartArtifactRef(
                artifact_id=str(a.artifact_id),
                url=f"/artifacts/{a.artifact_id}",
                type=a.artifact_type,
            )

    if status == "succeeded_empty":
        dataframe_preview: list = []
    else:
        dataframe_preview = final_state.get("dataframe_preview") or []

    session.commit()
    session.close()

    response = QueryResponse(
        thread_id=thread_id,
        run_id=run_id,
        response=final_text,
        route=RouteSummary(
            complexity=route.get("complexity"),
            selected_model=route.get("selected_model"),
            rationale=route.get("rationale"),
        ),
        sql=sql,
        code=(final_state.get("generated_code") if payload.debug else None),
        chart_artifact=chart_ref,
        dataframe_preview=dataframe_preview,
        row_count=int((final_state.get("validation_result") or {}).get("row_count") or 0),
        status=status,
        carryover=CarryoverInfo(
            turn_count=carryover_turn_count,
            preamble=carryover_preamble,
        ),
    )
    return response


# ─── /artifacts/{id} ──────────────────────────────────────────────────


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> FileResponse:
    factory = get_session_factory()
    session = factory()
    try:
        try:
            uid = UUID(artifact_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "artifact_not_found", "message": str(exc)}},
            ) from exc

        repo = ArtifactRepo(session)
        artifact = repo.get(uid)
        if artifact is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "artifact_not_found", "message": artifact_id}},
            )

        path = Path(artifact.path).resolve()
        artifacts_root = Path(settings.ARTIFACTS_DIR).resolve()
        try:
            path.relative_to(artifacts_root)
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "artifact_not_found", "message": "path outside ARTIFACTS_DIR"}},
            )
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "artifact_not_found", "message": "file missing"}},
            )

        return FileResponse(path=str(path), media_type="text/html")
    finally:
        session.close()


# ─── Initialization helper for tests ─────────────────────────────────


def initialize_for_tests(*, duckdb_path: str, artifacts_dir: str, db_url: str) -> None:
    """Test helper — point settings at fixture paths and rewire the
    schema cache + DB engine."""
    settings.ANALYTICS_DUCKDB_PATH = duckdb_path
    settings.ARTIFACTS_DIR = artifacts_dir
    settings.DATABASE_URL = db_url
    reset_schema_cache()
    from discogs_agent.persistence.db import init_engine, reset_engine
    from discogs_agent.persistence.models import Base

    reset_engine()
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    _set_graph(None)  # force rebuild on next /query
