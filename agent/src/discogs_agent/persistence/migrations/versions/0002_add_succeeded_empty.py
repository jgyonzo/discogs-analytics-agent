"""add succeeded_empty to agent_runs.status

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-01

Extends the agent_runs.status CHECK constraint with the new
`succeeded_empty` value introduced by feature
005-agent-schema-context. Empty-result runs (zero rows returned
by valid SQL) get this terminal state instead of a deceptive
`succeeded` with a blank chart.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


_OLD = (
    "status IN ('running','succeeded','failed_safety','failed_validation',"
    "'failed_unsupported','failed_clarification_needed','failed_internal')"
)
_NEW = (
    "status IN ('running','succeeded','succeeded_empty',"
    "'failed_safety','failed_validation',"
    "'failed_unsupported','failed_clarification_needed','failed_internal')"
)


def upgrade() -> None:
    op.drop_constraint(
        "agent_runs_status_check", "agent_runs", type_="check"
    )
    op.create_check_constraint(
        "agent_runs_status_check", "agent_runs", _NEW
    )


def downgrade() -> None:
    op.drop_constraint(
        "agent_runs_status_check", "agent_runs", type_="check"
    )
    op.create_check_constraint(
        "agent_runs_status_check", "agent_runs", _OLD
    )
