"""Thin DAOs per agent_* table.

These are intentionally narrow — they expose the queries the API and the
persistence shim need, nothing more.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from discogs_agent.persistence.models import (
    Artifact,
    Error,
    ModelUsage,
    Run,
    Thread,
    ToolCall,
)

# ─── Threads ──────────────────────────────────────────────────────────


class ThreadRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, metadata: dict[str, Any] | None = None) -> Thread:
        t = Thread(
            thread_id=uuid4(),
            status="active",
            metadata_json=metadata or {},
        )
        self.session.add(t)
        self.session.flush()
        return t

    def get(self, thread_id: UUID) -> Thread | None:
        return self.session.get(Thread, thread_id)

    def touch(self, thread_id: UUID) -> None:
        t = self.get(thread_id)
        if t is not None:
            t.updated_at = datetime.now(UTC)


# ─── Runs ─────────────────────────────────────────────────────────────


class RunRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, thread_id: UUID, user_query: str) -> Run:
        r = Run(
            run_id=uuid4(),
            thread_id=thread_id,
            user_query=user_query,
            status="running",
        )
        self.session.add(r)
        self.session.flush()
        return r

    def get(self, run_id: UUID) -> Run | None:
        return self.session.get(Run, run_id)

    def update_route(
        self,
        run_id: UUID,
        complexity: str,
        selected_model: str | None,
    ) -> None:
        r = self.get(run_id)
        if r is not None:
            r.complexity = complexity
            r.selected_model = selected_model

    def update_generated_sql(self, run_id: UUID, sql: str | None) -> None:
        r = self.get(run_id)
        if r is not None:
            r.generated_sql = sql

    def update_metadata(self, run_id: UUID, **fields: Any) -> None:
        r = self.get(run_id)
        if r is not None:
            md = dict(r.metadata_json)
            md.update(fields)
            r.metadata_json = md

    def finalize(
        self,
        run_id: UUID,
        status: str,
        final_response: str | None,
        latency_ms: int,
    ) -> None:
        r = self.get(run_id)
        if r is None:
            return
        r.status = status
        r.final_response = final_response
        r.finished_at = datetime.now(UTC)
        r.latency_ms = latency_ms

    def list_by_thread(
        self,
        thread_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        stmt = (
            select(Run)
            .where(Run.thread_id == thread_id)
            .order_by(Run.started_at)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def count_by_thread(self, thread_id: UUID) -> int:
        from sqlalchemy import func as _func

        stmt = select(_func.count()).select_from(Run).where(Run.thread_id == thread_id)
        return int(self.session.scalar(stmt) or 0)

    def fetch_recent_for_thread(
        self,
        thread_id: UUID,
        limit: int,
        statuses: tuple[str, ...] | list[str],
    ) -> list[Run]:
        """Return up to `limit` most recent runs of `thread_id` whose
        status is in `statuses`, ordered oldest-first within the
        returned window. Used by US4 carry-over.

        The two-step ordering — fetch DESC, return ASC — gives the
        newest N rows but in chronological order so the carry-over
        builder can prepend the most recent.
        """
        if limit <= 0 or not statuses:
            return []
        stmt = (
            select(Run)
            .where(Run.thread_id == thread_id)
            .where(Run.status.in_(tuple(statuses)))
            .order_by(Run.started_at.desc())
            .limit(limit)
        )
        rows = list(self.session.scalars(stmt))
        rows.reverse()  # oldest-first within the window
        return rows


# ─── Tool calls ───────────────────────────────────────────────────────


class ToolCallRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        run_id: UUID,
        node_name: str,
        tool_name: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any] | None,
        status: str,
        latency_ms: int,
        error_message: str | None,
    ) -> ToolCall:
        tc = ToolCall(
            tool_call_id=uuid4(),
            run_id=run_id,
            node_name=node_name,
            tool_name=tool_name,
            input_json=input_json,
            output_json=output_json,
            status=status,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        self.session.add(tc)
        self.session.flush()
        return tc

    def list_by_run(self, run_id: UUID) -> list[ToolCall]:
        stmt = select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at)
        return list(self.session.scalars(stmt))


# ─── Model usage ──────────────────────────────────────────────────────


class ModelUsageRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        run_id: UUID,
        node_name: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: Decimal | None,
        latency_ms: int,
    ) -> ModelUsage:
        mu = ModelUsage(
            usage_id=uuid4(),
            run_id=run_id,
            node_name=node_name,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
        )
        self.session.add(mu)
        self.session.flush()
        return mu

    def list_by_run(self, run_id: UUID) -> list[ModelUsage]:
        stmt = select(ModelUsage).where(ModelUsage.run_id == run_id).order_by(ModelUsage.created_at)
        return list(self.session.scalars(stmt))


# ─── Artifacts ────────────────────────────────────────────────────────


class ArtifactRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        run_id: UUID,
        thread_id: UUID,
        artifact_type: str,
        path: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        a = Artifact(
            artifact_id=uuid4(),
            run_id=run_id,
            thread_id=thread_id,
            artifact_type=artifact_type,
            path=path,
            metadata_json=metadata or {},
        )
        self.session.add(a)
        self.session.flush()
        return a

    def get(self, artifact_id: UUID) -> Artifact | None:
        return self.session.get(Artifact, artifact_id)

    def list_by_run(self, run_id: UUID) -> list[Artifact]:
        stmt = select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at)
        return list(self.session.scalars(stmt))


# ─── Errors ───────────────────────────────────────────────────────────


class ErrorRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        run_id: UUID,
        node_name: str,
        error_type: str,
        error_message: str,
        traceback: str | None = None,
    ) -> Error:
        e = Error(
            error_id=uuid4(),
            run_id=run_id,
            node_name=node_name,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback,
        )
        self.session.add(e)
        self.session.flush()
        return e

    def list_by_run(self, run_id: UUID) -> list[Error]:
        stmt = select(Error).where(Error.run_id == run_id).order_by(Error.created_at)
        return list(self.session.scalars(stmt))
