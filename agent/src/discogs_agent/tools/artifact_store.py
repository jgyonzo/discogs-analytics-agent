"""Tool: artifact_store.

Persists an artifact row in agent_artifacts after asserting the
filesystem path is inside ARTIFACTS_DIR.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.config import settings
from discogs_agent.observability.tracing import run_context
from discogs_agent.persistence.db import current_session
from discogs_agent.persistence.repositories import ArtifactRepo
from discogs_agent.tools.base import traced_tool


class ArtifactInput(BaseModel):
    run_id: str
    thread_id: str
    artifact_type: str
    path: str
    metadata: dict[str, Any] = {}


class ArtifactOutput(BaseModel):
    artifact_id: str
    url: str


def _assert_inside_artifacts_dir(path: str) -> Path:
    artifacts_dir = Path(settings.ARTIFACTS_DIR).resolve()
    p = Path(path).resolve()
    try:
        p.relative_to(artifacts_dir)
    except ValueError as exc:
        raise ValueError(f"artifact path {p} is outside ARTIFACTS_DIR={artifacts_dir}") from exc
    return p


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[ArtifactInput], ArtifactOutput]:
    @traced_tool("artifact_store", session_provider=session_provider)
    def artifact_store(payload: ArtifactInput) -> ArtifactOutput:
        if payload.artifact_type == "plotly_html" and not payload.path.endswith(".html"):
            raise ValueError(f"plotly_html artifact must be .html, got: {payload.path}")
        _assert_inside_artifacts_dir(payload.path)

        artifact_id_str = ""
        url = ""
        session = (session_provider or current_session)()
        if session is not None:
            run_id_str = payload.run_id or run_context.get()
            if run_id_str:
                repo = ArtifactRepo(session)
                row = repo.create(
                    run_id=UUID(run_id_str),
                    thread_id=UUID(payload.thread_id),
                    artifact_type=payload.artifact_type,
                    path=payload.path,
                    metadata=payload.metadata,
                )
                artifact_id_str = str(row.artifact_id)
                url = f"/artifacts/{artifact_id_str}"

        return ArtifactOutput(artifact_id=artifact_id_str, url=url)

    return artifact_store


artifact_store = _build()


def make_artifact_store(
    session_provider: Callable[[], Session | None],
) -> Callable[[ArtifactInput], ArtifactOutput]:
    return _build(session_provider)
