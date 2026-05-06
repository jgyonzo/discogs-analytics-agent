"""initial agent schema

Revision ID: 0001
Revises:
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine[object]:
    return PG_UUID(as_uuid=True).with_variant(sa.String(36), "sqlite")  # type: ignore[return-value]


def _json() -> sa.types.TypeEngine[object]:
    return JSONB().with_variant(sa.JSON(), "sqlite")


def _ts() -> sa.types.TypeEngine[object]:
    return sa.TIMESTAMP(timezone=True).with_variant(sa.TIMESTAMP(timezone=False), "sqlite")  # type: ignore[return-value]


def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("thread_id", _uuid(), primary_key=True),
        sa.Column("created_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("metadata_json", _json(), server_default="{}", nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="agent_threads_status_check",
        ),
    )

    op.create_table(
        "agent_runs",
        sa.Column("run_id", _uuid(), primary_key=True),
        sa.Column(
            "thread_id",
            _uuid(),
            sa.ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("complexity", sa.String(32)),
        sa.Column("selected_model", sa.String(64)),
        sa.Column("status", sa.String(32), server_default="running", nullable=False),
        sa.Column("started_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", _ts()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("final_response", sa.Text()),
        sa.Column("generated_sql", sa.Text()),
        sa.Column("metadata_json", _json(), server_default="{}", nullable=False),
        sa.CheckConstraint(
            "complexity IS NULL OR complexity IN "
            "('simple','complex','unsupported','clarification_needed')",
            name="agent_runs_complexity_check",
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed_safety','failed_validation',"
            "'failed_unsupported','failed_clarification_needed','failed_internal')",
            name="agent_runs_status_check",
        ),
    )
    op.create_index("agent_runs_thread_id_idx", "agent_runs", ["thread_id"])
    op.create_index("agent_runs_started_at_idx", "agent_runs", ["started_at"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("tool_call_id", _uuid(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid(),
            sa.ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("input_json", _json(), nullable=False),
        sa.Column("output_json", _json()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded','failed')",
            name="agent_tool_calls_status_check",
        ),
    )
    op.create_index("agent_tool_calls_run_id_idx", "agent_tool_calls", ["run_id"])

    op.create_table(
        "agent_model_usage",
        sa.Column("usage_id", _uuid(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid(),
            sa.ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6)),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "total_tokens = prompt_tokens + completion_tokens",
            name="agent_model_usage_total_check",
        ),
    )
    op.create_index("agent_model_usage_run_id_idx", "agent_model_usage", ["run_id"])

    op.create_table(
        "agent_artifacts",
        sa.Column("artifact_id", _uuid(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid(),
            sa.ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            _uuid(),
            sa.ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("metadata_json", _json(), server_default="{}", nullable=False),
        sa.Column("created_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "artifact_type IN ('plotly_html')",
            name="agent_artifacts_type_check",
        ),
    )
    op.create_index("agent_artifacts_run_id_idx", "agent_artifacts", ["run_id"])
    op.create_index("agent_artifacts_thread_id_idx", "agent_artifacts", ["thread_id"])

    op.create_table(
        "agent_errors",
        sa.Column("error_id", _uuid(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid(),
            sa.ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("error_type", sa.String(64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text()),
        sa.Column("created_at", _ts(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "error_type IN ('safety_violation','sandbox_timeout',"
            "'sandbox_exception','validation_failed','unexpected')",
            name="agent_errors_type_check",
        ),
    )
    op.create_index("agent_errors_run_id_idx", "agent_errors", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_errors")
    op.drop_table("agent_artifacts")
    op.drop_table("agent_model_usage")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_runs")
    op.drop_table("agent_threads")
