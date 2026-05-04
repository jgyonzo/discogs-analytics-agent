"""SQLAlchemy 2.x ORM models for the six agent_* tables.

Type adaptations are dialect-aware:
  - PG_UUID  → CHAR(36) on SQLite
  - JSONB    → JSON      on SQLite
  - TIMESTAMPTZ → TIMESTAMP on SQLite

Achieved via SQLAlchemy's `with_variant`, so the same model definitions
work in both contexts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import JSON, TIMESTAMP


class GUID(TypeDecorator[UUID]):
    """Platform-portable UUID:
    - Postgres: native UUID column.
    - Other dialects (SQLite): CHAR(36) string round-tripped to UUID.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(  # type: ignore[override]
        self, value: UUID | str | None, dialect: Dialect
    ) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, UUID) else UUID(str(value))
        return str(value) if isinstance(value, UUID) else str(value)

    def process_result_value(  # type: ignore[override]
        self, value: Any, dialect: Dialect
    ) -> UUID | None:
        if value is None:
            return None
        return value if isinstance(value, UUID) else UUID(str(value))


UUIDType = GUID
JSONType = JSONB().with_variant(JSON(), "sqlite")
TIMESTAMPType = TIMESTAMP(timezone=True).with_variant(TIMESTAMP(timezone=False), "sqlite")


class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "agent_threads"

    thread_id: Mapped[UUID] = mapped_column(UUIDType, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="thread")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="agent_threads_status_check",
        ),
    )


class Run(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[UUID] = mapped_column(UUIDType, primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(
        UUIDType,
        ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    complexity: Mapped[str | None] = mapped_column(String(32))
    selected_model: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPType)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    final_response: Mapped[str | None] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )

    thread: Mapped[Thread] = relationship(back_populates="runs")
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    model_usage: Mapped[list[ModelUsage]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    errors: Mapped[list[Error]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "complexity IS NULL OR complexity IN "
            "('simple','complex','unsupported','clarification_needed')",
            name="agent_runs_complexity_check",
        ),
        CheckConstraint(
            "status IN ('running','succeeded','succeeded_empty',"
            "'failed_safety','failed_validation',"
            "'failed_unsupported','failed_clarification_needed','failed_internal')",
            name="agent_runs_status_check",
        ),
        Index("agent_runs_thread_id_idx", "thread_id"),
        Index("agent_runs_started_at_idx", "started_at"),
    )


class ToolCall(Base):
    __tablename__ = "agent_tool_calls"

    tool_call_id: Mapped[UUID] = mapped_column(UUIDType, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        UUIDType,
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="tool_calls")

    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded','failed')",
            name="agent_tool_calls_status_check",
        ),
        Index("agent_tool_calls_run_id_idx", "run_id"),
    )


class ModelUsage(Base):
    __tablename__ = "agent_model_usage"

    usage_id: Mapped[UUID] = mapped_column(UUIDType, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        UUIDType,
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="model_usage")

    __table_args__ = (
        CheckConstraint(
            "total_tokens = prompt_tokens + completion_tokens",
            name="agent_model_usage_total_check",
        ),
        Index("agent_model_usage_run_id_idx", "run_id"),
    )


class Artifact(Base):
    __tablename__ = "agent_artifacts"

    artifact_id: Mapped[UUID] = mapped_column(UUIDType, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        UUIDType,
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[UUID] = mapped_column(
        UUIDType,
        ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="artifacts")
    thread: Mapped[Thread] = relationship(back_populates="artifacts")

    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('plotly_html')",
            name="agent_artifacts_type_check",
        ),
        Index("agent_artifacts_run_id_idx", "run_id"),
        Index("agent_artifacts_thread_id_idx", "thread_id"),
    )


class Error(Base):
    __tablename__ = "agent_errors"

    error_id: Mapped[UUID] = mapped_column(UUIDType, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        UUIDType,
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPType, nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="errors")

    __table_args__ = (
        CheckConstraint(
            "error_type IN ('safety_violation','sandbox_timeout',"
            "'sandbox_exception','validation_failed','unexpected')",
            name="agent_errors_type_check",
        ),
        Index("agent_errors_run_id_idx", "run_id"),
    )
