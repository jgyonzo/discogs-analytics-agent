# Contract: Postgres Schema

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md)
**Logical model**: [../data-model.md §1](../data-model.md).

DDL-flavored description of the six `agent_*` tables. Authored
so a reviewer can read the SQL and a SQLAlchemy 2.x model
side-by-side and see the same shape.

The migration that creates these tables is
`agent/src/discogs_agent/persistence/migrations/versions/0001_initial.py`.
This document is what the migration encodes; if they drift,
the migration is the source of truth and this document is the
bug.

---

## 1. DDL

```sql
-- Threads
CREATE TABLE agent_threads (
    thread_id      UUID            PRIMARY KEY,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
    status         VARCHAR(32)     NOT NULL DEFAULT 'active',
    metadata_json  JSONB           NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT agent_threads_status_check
        CHECK (status IN ('active', 'archived'))
);

-- Runs
CREATE TABLE agent_runs (
    run_id          UUID           PRIMARY KEY,
    thread_id       UUID           NOT NULL REFERENCES agent_threads(thread_id) ON DELETE CASCADE,
    user_query      TEXT           NOT NULL,
    complexity      VARCHAR(32),
    selected_model  VARCHAR(64),
    status          VARCHAR(32)    NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    latency_ms      INTEGER,
    final_response  TEXT,
    generated_sql   TEXT,
    metadata_json   JSONB          NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT agent_runs_complexity_check
        CHECK (complexity IS NULL OR complexity IN ('simple','complex','unsupported','clarification_needed')),
    CONSTRAINT agent_runs_status_check
        CHECK (status IN ('running','succeeded','failed_safety','failed_validation','failed_unsupported','failed_clarification_needed','failed_internal'))
);
CREATE INDEX agent_runs_thread_id_idx     ON agent_runs (thread_id);
CREATE INDEX agent_runs_started_at_idx    ON agent_runs (started_at DESC);

-- Tool calls
CREATE TABLE agent_tool_calls (
    tool_call_id    UUID           PRIMARY KEY,
    run_id          UUID           NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    node_name       VARCHAR(64)    NOT NULL,
    tool_name       VARCHAR(64)    NOT NULL,
    input_json      JSONB          NOT NULL,
    output_json     JSONB,
    status          VARCHAR(32)    NOT NULL,
    latency_ms      INTEGER        NOT NULL,
    error_message   TEXT,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT agent_tool_calls_status_check
        CHECK (status IN ('succeeded','failed'))
);
CREATE INDEX agent_tool_calls_run_id_idx  ON agent_tool_calls (run_id);

-- Model usage
CREATE TABLE agent_model_usage (
    usage_id            UUID           PRIMARY KEY,
    run_id              UUID           NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    node_name           VARCHAR(64)    NOT NULL,
    model_name          VARCHAR(64)    NOT NULL,
    prompt_tokens       INTEGER        NOT NULL,
    completion_tokens   INTEGER        NOT NULL,
    total_tokens        INTEGER        NOT NULL,
    estimated_cost_usd  NUMERIC(10,6),
    latency_ms          INTEGER        NOT NULL,
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT agent_model_usage_total_check
        CHECK (total_tokens = prompt_tokens + completion_tokens)
);
CREATE INDEX agent_model_usage_run_id_idx ON agent_model_usage (run_id);

-- Artifacts
CREATE TABLE agent_artifacts (
    artifact_id     UUID           PRIMARY KEY,
    run_id          UUID           NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    thread_id       UUID           NOT NULL REFERENCES agent_threads(thread_id) ON DELETE CASCADE,
    artifact_type   VARCHAR(32)    NOT NULL,
    path            TEXT           NOT NULL,
    metadata_json   JSONB          NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT agent_artifacts_type_check
        CHECK (artifact_type IN ('plotly_html'))
);
CREATE INDEX agent_artifacts_run_id_idx    ON agent_artifacts (run_id);
CREATE INDEX agent_artifacts_thread_id_idx ON agent_artifacts (thread_id);

-- Errors
CREATE TABLE agent_errors (
    error_id        UUID           PRIMARY KEY,
    run_id          UUID           NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    node_name       VARCHAR(64)    NOT NULL,
    error_type      VARCHAR(64)    NOT NULL,
    error_message   TEXT           NOT NULL,
    traceback       TEXT,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT agent_errors_type_check
        CHECK (error_type IN ('safety_violation','sandbox_timeout','sandbox_exception','validation_failed','unexpected'))
);
CREATE INDEX agent_errors_run_id_idx ON agent_errors (run_id);
```

---

## 2. SQLAlchemy 2.x mapping (excerpt)

The ORM models live in
`agent/src/discogs_agent/persistence/models.py`. Sketch:

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import ForeignKey, CheckConstraint, Index, String, Text, Integer, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, TIMESTAMP

class Base(DeclarativeBase): pass

class Thread(Base):
    __tablename__ = "agent_threads"
    thread_id:      Mapped[UUID]      = mapped_column(PG_UUID, primary_key=True)
    created_at:     Mapped[datetime]  = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at:     Mapped[datetime]  = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status:         Mapped[str]       = mapped_column(String(32), nullable=False, default="active")
    metadata_json:  Mapped[dict]      = mapped_column(JSONB, nullable=False, default=dict)
    runs:           Mapped[list["Run"]]      = relationship(back_populates="thread", cascade="all, delete-orphan")
    artifacts:      Mapped[list["Artifact"]] = relationship(back_populates="thread")

class Run(Base):
    __tablename__ = "agent_runs"
    run_id:         Mapped[UUID]       = mapped_column(PG_UUID, primary_key=True)
    thread_id:      Mapped[UUID]       = mapped_column(PG_UUID, ForeignKey("agent_threads.thread_id", ondelete="CASCADE"), nullable=False)
    user_query:     Mapped[str]        = mapped_column(Text, nullable=False)
    complexity:     Mapped[str | None] = mapped_column(String(32))
    selected_model: Mapped[str | None] = mapped_column(String(64))
    status:         Mapped[str]        = mapped_column(String(32), nullable=False, default="running")
    started_at:     Mapped[datetime]   = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    finished_at:    Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    latency_ms:     Mapped[int | None]      = mapped_column(Integer)
    final_response: Mapped[str | None]      = mapped_column(Text)
    generated_sql:  Mapped[str | None]      = mapped_column(Text)
    metadata_json:  Mapped[dict]            = mapped_column(JSONB, nullable=False, default=dict)
    thread:         Mapped[Thread]          = relationship(back_populates="runs")
    tool_calls:     Mapped[list["ToolCall"]]   = relationship(back_populates="run", cascade="all, delete-orphan")
    model_usage:    Mapped[list["ModelUsage"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts:      Mapped[list["Artifact"]]   = relationship(back_populates="run", cascade="all, delete-orphan")
    errors:         Mapped[list["Error"]]      = relationship(back_populates="run", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("complexity IS NULL OR complexity IN ('simple','complex','unsupported','clarification_needed')"),
        CheckConstraint("status IN ('running','succeeded','failed_safety','failed_validation','failed_unsupported','failed_clarification_needed','failed_internal')"),
        Index("agent_runs_thread_id_idx", "thread_id"),
        Index("agent_runs_started_at_idx", "started_at"),
    )

# ... ToolCall, ModelUsage, Artifact, Error analogous
```

---

## 3. SQLite portability (test stratum)

The unit/graph-path test stratum runs against SQLite (R-07).
Adaptations:

| Postgres type | SQLite equivalent (via SQLAlchemy) | Note |
|---------------|------------------------------------|------|
| `UUID` | `CHAR(36)` | The `PG_UUID` column type is replaced by `String(36)` at the test-engine config level, transparent to model code. |
| `JSONB` | `JSON` | SQLAlchemy `JSON` abstracts both; serialization is byte-equal. |
| `TIMESTAMPTZ` | `TIMESTAMP` | SQLite stores as ISO string; SQLAlchemy's adapter handles tz conversion. |
| `NUMERIC(10,6)` | `NUMERIC` | SQLAlchemy `Numeric` works in both. |
| `CHECK` constraints | `CHECK` constraints | both honor them. |

The `tests/conftest.py` provides a `db_engine` fixture that
returns a Postgres engine when integration tests request it,
and SQLite (`:memory:`) otherwise.

---

## 4. Migrations

```text
agent/src/discogs_agent/persistence/migrations/
├── env.py                # Alembic env, reads DATABASE_URL from settings
├── alembic.ini           # template; generated alongside the package
└── versions/
    └── 0001_initial.py   # all six tables + indexes + constraints
```

Operator commands (documented in
[`../quickstart.md`](../quickstart.md)):

```bash
# Apply migrations:
docker compose exec agent-api alembic upgrade head

# Or, on first boot, the API service runs `alembic upgrade head`
# in its entrypoint before starting uvicorn (idempotent).
```

V1 ships exactly one migration. Subsequent specs add new
migrations under `versions/`.

---

## 5. Inspection-API query patterns

The inspection endpoints map cleanly to single-join queries:

```sql
-- GET /threads/{thread_id}
SELECT t.*,
       (SELECT COUNT(*) FROM agent_runs r WHERE r.thread_id = t.thread_id) AS run_count
FROM agent_threads t
WHERE t.thread_id = :thread_id;

SELECT r.*, a.artifact_id AS primary_artifact_id, a.artifact_type
FROM agent_runs r
LEFT JOIN LATERAL (
    SELECT artifact_id, artifact_type FROM agent_artifacts
    WHERE run_id = r.run_id
    ORDER BY created_at LIMIT 1
) a ON TRUE
WHERE r.thread_id = :thread_id
ORDER BY r.started_at;

-- GET /runs/{run_id} → 4 separate selects (run + tool_calls + model_usage + errors + artifacts)
-- joined in the API layer rather than via a single mega-join for legibility.
```

---

## 6. Backward-compat & seeds

V1 ships **no seed data**. A fresh Postgres comes up empty;
the first `/query` populates everything.

Future migrations will follow Alembic conventions (one file
per concern, autogenerated diff reviewed by hand). Drops or
column-type changes go through a deprecation cycle —
columns are added as nullable first, backfilled, then made
NOT NULL in a follow-up.

For V1, no such cycles apply: this is the initial schema.
