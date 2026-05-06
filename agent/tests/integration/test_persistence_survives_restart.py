"""US2 / T082 — persistence durability across a simulated process restart.

We can't exec a real ``docker compose down && up`` from inside pytest,
but the load-bearing invariant is *"the rows survive when SQLAlchemy's
engine is torn down and rebuilt against the same backing store"*.
Anchors SC-009 at the persistence layer; the docker-smoke test
(T083) covers the full container-level restart.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from discogs_agent.persistence.db import (
    engine_factory,
    init_engine,
    reset_engine,
)
from discogs_agent.persistence.models import Base
from discogs_agent.persistence.repositories import RunRepo, ThreadRepo


def test_thread_and_run_survive_engine_recycle(tmp_path: Path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'agent.sqlite'}"

    # Round 1 — write a thread + run.
    reset_engine()
    engine_a = init_engine(db_url)
    Base.metadata.create_all(engine_a)
    from sqlalchemy.orm import sessionmaker

    SessionA = sessionmaker(bind=engine_a, expire_on_commit=False, future=True)
    session_a = SessionA()
    try:
        thread = ThreadRepo(session_a).create()
        run = RunRepo(session_a).create(thread.thread_id, "first query")
        thread_id = thread.thread_id
        run_id = run.run_id
        session_a.commit()
    finally:
        session_a.close()
    engine_a.dispose()
    reset_engine()

    # Round 2 — fresh engine pointed at the same file.
    engine_b = engine_factory(db_url)
    SessionB = sessionmaker(bind=engine_b, expire_on_commit=False, future=True)
    session_b = SessionB()
    try:
        thread_again = ThreadRepo(session_b).get(thread_id)
        run_again = RunRepo(session_b).get(run_id)
        assert thread_again is not None
        assert run_again is not None
        assert run_again.user_query == "first query"
        assert run_again.status == "running"
        assert run_again.thread_id == thread_id
    finally:
        session_b.close()
        engine_b.dispose()


def test_finalized_run_survives_engine_recycle(tmp_path: Path) -> None:
    """Same shape but with a fully-finalized run (status, latency, response)."""
    db_url = f"sqlite+pysqlite:///{tmp_path / 'agent.sqlite'}"

    reset_engine()
    engine_a = init_engine(db_url)
    Base.metadata.create_all(engine_a)
    from sqlalchemy.orm import sessionmaker

    SessionA = sessionmaker(bind=engine_a, expire_on_commit=False, future=True)
    session_a = SessionA()
    try:
        thread = ThreadRepo(session_a).create()
        run_repo = RunRepo(session_a)
        run = run_repo.create(thread.thread_id, "trend query")
        run_repo.update_route(run.run_id, complexity="simple", selected_model="gpt-4o-mini")
        run_repo.update_generated_sql(
            run.run_id,
            "SELECT decade, COUNT(DISTINCT release_id) FROM release_fact "
            "WHERE style = 'Techno' GROUP BY decade",
        )
        run_repo.finalize(
            run.run_id,
            status="succeeded",
            final_response="Generated a chart of Techno releases by decade.",
            latency_ms=1234,
        )
        run_id: UUID = run.run_id
        session_a.commit()
    finally:
        session_a.close()
    engine_a.dispose()
    reset_engine()

    engine_b = engine_factory(db_url)
    SessionB = sessionmaker(bind=engine_b, expire_on_commit=False, future=True)
    session_b = SessionB()
    try:
        run_again = RunRepo(session_b).get(run_id)
        assert run_again is not None
        assert run_again.status == "succeeded"
        assert run_again.complexity == "simple"
        assert run_again.selected_model == "gpt-4o-mini"
        assert run_again.latency_ms == 1234
        assert run_again.generated_sql is not None
        assert "release_fact" in run_again.generated_sql
        assert run_again.final_response is not None
        assert "Techno" in run_again.final_response
    finally:
        session_b.close()
        engine_b.dispose()


@pytest.mark.skipif(
    "AGENT_USE_POSTGRES" not in __import__("os").environ,
    reason="AGENT_USE_POSTGRES=1 (testcontainers) required",
)
def test_run_survives_engine_recycle_against_postgres() -> None:
    """When AGENT_USE_POSTGRES=1, also exercise the same invariant
    against a real Postgres — the production target."""
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    pg = PostgresContainer("postgres:16-alpine")
    pg.start()
    try:
        url = pg.get_connection_url().replace("psycopg2", "psycopg")

        reset_engine()
        engine_a = init_engine(url)
        Base.metadata.create_all(engine_a)
        from sqlalchemy.orm import sessionmaker

        SessionA = sessionmaker(bind=engine_a, expire_on_commit=False, future=True)
        session_a = SessionA()
        try:
            thread = ThreadRepo(session_a).create()
            run = RunRepo(session_a).create(thread.thread_id, "pg query")
            run_id = run.run_id
            session_a.commit()
        finally:
            session_a.close()
        engine_a.dispose()
        reset_engine()

        engine_b = engine_factory(url)
        SessionB = sessionmaker(bind=engine_b, expire_on_commit=False, future=True)
        session_b = SessionB()
        try:
            run_again = RunRepo(session_b).get(run_id)
            assert run_again is not None
            assert run_again.user_query == "pg query"
        finally:
            session_b.close()
            engine_b.dispose()
    finally:
        pg.stop()
