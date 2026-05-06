"""Shared pytest fixtures.

Provides:
  - `db_engine`     : SQLite in-memory by default; Postgres via
                      testcontainers when `AGENT_USE_POSTGRES=1`.
  - `db_session`    : a fresh SQLAlchemy session bound to db_engine.
  - `seed_duckdb`   : path to the committed seed.duckdb fixture.
  - `seed_duckdb_no_master` : path to seed_no_master.duckdb.
  - `llm_stub`      : forces settings.LLM_BACKEND="stub" + clears
                      stub state between tests.
  - `tmp_artifact_dir` : a fresh writable artifact dir per test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from discogs_agent.config import settings
from discogs_agent.persistence.db import engine_factory
from discogs_agent.persistence.models import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ─── Database engine ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    if os.environ.get("AGENT_USE_POSTGRES") == "1":
        pytest.importorskip("testcontainers.postgres")
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:16-alpine") as pg:
            url = pg.get_connection_url().replace("psycopg2", "psycopg")
            engine = engine_factory(url)
            Base.metadata.create_all(engine)
            try:
                yield engine
            finally:
                engine.dispose()
    else:
        engine = engine_factory("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.rollback()  # tests should commit explicitly if they care
    finally:
        # Clean every table so the next test starts fresh.
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


# ─── Seed DuckDB fixtures ─────────────────────────────────────────────


def _import_seed_builder() -> object:
    """Import the seed builder via direct file load — survives any
    pytest rootdir or PYTHONPATH config."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_agent_tests_seed_duckdb",
        FIXTURES_DIR / "seed_duckdb.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def seed_duckdb() -> Path:
    path = FIXTURES_DIR / "seed.duckdb"
    if not path.exists():
        builder = _import_seed_builder()
        builder.build_seed_duckdb(path, with_master_fact=True)  # type: ignore[attr-defined]
    return path


@pytest.fixture(scope="session")
def seed_duckdb_no_master() -> Path:
    path = FIXTURES_DIR / "seed_no_master.duckdb"
    if not path.exists():
        builder = _import_seed_builder()
        builder.build_seed_duckdb(path, with_master_fact=False)  # type: ignore[attr-defined]
    return path


# ─── LLM stub ─────────────────────────────────────────────────────────


@pytest.fixture
def llm_stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from discogs_agent.llm import stub as stub_module

    monkeypatch.setattr(settings, "LLM_BACKEND", "stub")
    stub_module.reset()
    try:
        yield
    finally:
        stub_module.reset()


# ─── Tmp artifact dir ─────────────────────────────────────────────────


@pytest.fixture
def tmp_artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir()
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", str(d))
    return d


# ─── DuckDB path override ─────────────────────────────────────────────


@pytest.fixture
def use_seed_duckdb(seed_duckdb: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point settings.ANALYTICS_DUCKDB_PATH at the seed DuckDB and
    reset the schema cache."""
    from discogs_agent.duckdb_layer import schema as schema_module

    monkeypatch.setattr(settings, "ANALYTICS_DUCKDB_PATH", str(seed_duckdb))
    schema_module.reset_schema_cache()
    return seed_duckdb


@pytest.fixture
def use_seed_duckdb_no_master(
    seed_duckdb_no_master: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    from discogs_agent.duckdb_layer import schema as schema_module

    monkeypatch.setattr(settings, "ANALYTICS_DUCKDB_PATH", str(seed_duckdb_no_master))
    schema_module.reset_schema_cache()
    return seed_duckdb_no_master


# ─── Full agent environment (graph + integration tests) ──────────────


@pytest.fixture
def agent_env(seed_duckdb: Path, tmp_path: Path) -> Iterator[dict]:
    """Wire settings, the engine, and the LLM stub for the duration
    of one test. Returns a dict with the post_query handle."""
    from discogs_agent.api_query import (
        QueryRequest,
        initialize_for_tests,
        post_query,
    )
    from discogs_agent.llm import stub as stub_module

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    db_url = f"sqlite+pysqlite:///{tmp_path / 'agent.sqlite'}"

    prior_backend = settings.LLM_BACKEND
    settings.LLM_BACKEND = "stub"

    initialize_for_tests(
        duckdb_path=str(seed_duckdb),
        artifacts_dir=str(artifacts),
        db_url=db_url,
    )
    stub_module.reset()

    yield {
        "artifacts": artifacts,
        "db_url": db_url,
        "duckdb_path": str(seed_duckdb),
        "post_query": post_query,
        "QueryRequest": QueryRequest,
    }

    stub_module.reset()
    settings.LLM_BACKEND = prior_backend


@pytest.fixture
def agent_env_no_master(seed_duckdb_no_master: Path, tmp_path: Path) -> Iterator[dict]:
    """Same as agent_env but pointed at the master_fact-less seed."""
    from discogs_agent.api_query import (
        QueryRequest,
        initialize_for_tests,
        post_query,
    )
    from discogs_agent.llm import stub as stub_module

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    db_url = f"sqlite+pysqlite:///{tmp_path / 'agent.sqlite'}"

    prior_backend = settings.LLM_BACKEND
    settings.LLM_BACKEND = "stub"

    initialize_for_tests(
        duckdb_path=str(seed_duckdb_no_master),
        artifacts_dir=str(artifacts),
        db_url=db_url,
    )
    stub_module.reset()

    yield {
        "artifacts": artifacts,
        "db_url": db_url,
        "duckdb_path": str(seed_duckdb_no_master),
        "post_query": post_query,
        "QueryRequest": QueryRequest,
    }

    stub_module.reset()
    settings.LLM_BACKEND = prior_backend
