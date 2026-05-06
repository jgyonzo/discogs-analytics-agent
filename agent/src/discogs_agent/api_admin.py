"""US3 inspection endpoints — /runs/{id} and /threads/{id}.

Admin-aware: ``generated_code`` and ``errors[].traceback`` are
populated only when the request authenticates with
``X-Agent-Admin: <token>`` matching ``settings.AGENT_ADMIN_TOKEN``.
Empty token disables admin mode entirely (default deny).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.api import app
from discogs_agent.config import settings
from discogs_agent.persistence.db import get_session_factory
from discogs_agent.persistence.models import Artifact, Run
from discogs_agent.persistence.repositories import (
    ArtifactRepo,
    ErrorRepo,
    ModelUsageRepo,
    RunRepo,
    ThreadRepo,
    ToolCallRepo,
)


# ─── Auth dependency ──────────────────────────────────────────────────


def is_admin(request: Request) -> bool:
    token = settings.AGENT_ADMIN_TOKEN
    if not token:
        return False
    presented = request.headers.get("X-Agent-Admin")
    return presented is not None and presented == token


# ─── DTOs ─────────────────────────────────────────────────────────────


class ArtifactRef(BaseModel):
    artifact_id: str
    url: str
    type: str


class ToolCallDTO(BaseModel):
    tool_call_id: str
    node_name: str
    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    status: str
    latency_ms: int
    created_at: datetime


class ModelUsageDTO(BaseModel):
    usage_id: str
    node_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    latency_ms: int
    created_at: datetime


class ErrorDTO(BaseModel):
    error_id: str
    node_name: str
    error_type: str
    error_message: str
    traceback: str | None
    created_at: datetime


class ArtifactDTO(BaseModel):
    artifact_id: str
    type: str
    url: str
    metadata: dict[str, Any]
    created_at: datetime


class RunMetadataDTO(BaseModel):
    carryover: dict[str, Any] | None
    route_rationale: str | None
    retry_count: int


class RunDTO(BaseModel):
    run_id: str
    thread_id: str
    user_query: str
    status: str
    complexity: str | None
    selected_model: str | None
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None
    final_response: str | None
    generated_sql: str | None
    generated_code: str | None
    metadata: RunMetadataDTO
    tool_calls: list[ToolCallDTO]
    model_usage: list[ModelUsageDTO]
    errors: list[ErrorDTO]
    artifacts: list[ArtifactDTO]


class RunSummaryDTO(BaseModel):
    run_id: str
    user_query: str
    complexity: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None
    primary_artifact: ArtifactRef | None


class ThreadDTO(BaseModel):
    thread_id: str
    created_at: datetime
    updated_at: datetime
    status: str
    run_count: int
    runs: list[RunSummaryDTO]


# ─── Serializers ──────────────────────────────────────────────────────


def _serialize_run(session: Session, run: Run, *, admin: bool) -> RunDTO:
    tool_calls = ToolCallRepo(session).list_by_run(run.run_id)
    model_usage = ModelUsageRepo(session).list_by_run(run.run_id)
    errors = ErrorRepo(session).list_by_run(run.run_id)
    artifacts = ArtifactRepo(session).list_by_run(run.run_id)

    md = run.metadata_json or {}
    generated_code_raw = md.get("generated_code")

    return RunDTO(
        run_id=str(run.run_id),
        thread_id=str(run.thread_id),
        user_query=run.user_query,
        status=run.status,
        complexity=run.complexity,
        selected_model=run.selected_model,
        started_at=run.started_at,
        finished_at=run.finished_at,
        latency_ms=run.latency_ms,
        final_response=run.final_response,
        generated_sql=run.generated_sql,
        generated_code=(generated_code_raw if admin else None),
        metadata=RunMetadataDTO(
            carryover=md.get("carryover"),
            route_rationale=md.get("route_rationale"),
            retry_count=int(md.get("retry_count") or 0),
        ),
        tool_calls=[
            ToolCallDTO(
                tool_call_id=str(tc.tool_call_id),
                node_name=tc.node_name,
                tool_name=tc.tool_name,
                input=tc.input_json or {},
                output=tc.output_json,
                status=tc.status,
                latency_ms=tc.latency_ms,
                created_at=tc.created_at,
            )
            for tc in tool_calls
        ],
        model_usage=[
            ModelUsageDTO(
                usage_id=str(mu.usage_id),
                node_name=mu.node_name,
                model_name=mu.model_name,
                prompt_tokens=mu.prompt_tokens,
                completion_tokens=mu.completion_tokens,
                total_tokens=mu.total_tokens,
                estimated_cost_usd=(
                    float(mu.estimated_cost_usd)
                    if mu.estimated_cost_usd is not None
                    else None
                ),
                latency_ms=mu.latency_ms,
                created_at=mu.created_at,
            )
            for mu in model_usage
        ],
        errors=[
            ErrorDTO(
                error_id=str(e.error_id),
                node_name=e.node_name,
                error_type=e.error_type,
                error_message=e.error_message,
                traceback=(e.traceback if admin else None),
                created_at=e.created_at,
            )
            for e in errors
        ],
        artifacts=[
            ArtifactDTO(
                artifact_id=str(a.artifact_id),
                type=a.artifact_type,
                url=f"/artifacts/{a.artifact_id}",
                metadata=a.metadata_json or {},
                created_at=a.created_at,
            )
            for a in artifacts
        ],
    )


def _earliest_artifact_for_run(session: Session, run_id: UUID) -> Artifact | None:
    artifacts = ArtifactRepo(session).list_by_run(run_id)
    return artifacts[0] if artifacts else None


# ─── Routes ───────────────────────────────────────────────────────────


@app.get("/runs/{run_id}", response_model=RunDTO)
def get_run(run_id: str, admin: bool = Depends(is_admin)) -> RunDTO:
    try:
        uid = UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "run_not_found", "message": str(exc)}},
        ) from exc

    factory = get_session_factory()
    session = factory()
    try:
        run = RunRepo(session).get(uid)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "run_not_found", "message": run_id}},
            )
        return _serialize_run(session, run, admin=admin)
    finally:
        session.close()


@app.get("/threads/{thread_id}", response_model=ThreadDTO)
def get_thread(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ThreadDTO:
    try:
        tid = UUID(thread_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "thread_not_found", "message": str(exc)}},
        ) from exc

    factory = get_session_factory()
    session = factory()
    try:
        thread = ThreadRepo(session).get(tid)
        if thread is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "thread_not_found", "message": thread_id}},
            )

        run_repo = RunRepo(session)
        run_count = run_repo.count_by_thread(tid)
        page_runs = run_repo.list_by_thread(tid, limit=limit, offset=offset)

        run_summaries: list[RunSummaryDTO] = []
        for r in page_runs:
            artifact = _earliest_artifact_for_run(session, r.run_id)
            primary = (
                ArtifactRef(
                    artifact_id=str(artifact.artifact_id),
                    url=f"/artifacts/{artifact.artifact_id}",
                    type=artifact.artifact_type,
                )
                if artifact is not None
                else None
            )
            run_summaries.append(
                RunSummaryDTO(
                    run_id=str(r.run_id),
                    user_query=r.user_query,
                    complexity=r.complexity,
                    status=r.status,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    latency_ms=r.latency_ms,
                    primary_artifact=primary,
                )
            )

        return ThreadDTO(
            thread_id=str(thread.thread_id),
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            status=thread.status,
            run_count=run_count,
            runs=run_summaries,
        )
    finally:
        session.close()
