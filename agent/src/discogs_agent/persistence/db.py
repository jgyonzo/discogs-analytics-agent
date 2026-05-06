"""SQLAlchemy engine + session factories.

A single module-level engine is used in production. Tests inject their
own engine via the conftest fixtures.

`session_context` is a ContextVar that the API sets per request so
@traced_tool can persist to the same session without each node having
to thread it through.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from discogs_agent.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

session_context: ContextVar[Session | None] = ContextVar("agent_session", default=None)


@contextmanager
def use_session(session: Session) -> Iterator[None]:
    """Bind `session` for the duration of a request. The @traced_tool
    decorator and the cost_logger / artifact_store tools fall back to
    this when no explicit session_provider was wired."""
    token = session_context.set(session)
    try:
        yield
    finally:
        session_context.reset(token)


def current_session() -> Session | None:
    """Return the request-scoped session, or None when not inside a
    `use_session` block."""
    return session_context.get()


def engine_factory(url: str) -> Engine:
    """Build an engine for the given URL. SQLite gets check_same_thread=False
    so FastAPI's threadpool can share the engine."""
    if url.startswith("sqlite"):
        return create_engine(url, future=True, connect_args={"check_same_thread": False})
    return create_engine(url, future=True, pool_pre_ping=True)


def init_engine(url: str | None = None) -> Engine:
    """Set the module-level engine. Called from FastAPI startup."""
    global _engine, _SessionLocal
    _engine = engine_factory(url or settings.DATABASE_URL)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_session() -> Iterator[Session]:
    """FastAPI dependency. Yields a session and closes it."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test helper — drop the cached engine and force re-init."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
