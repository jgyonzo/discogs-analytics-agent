"""Tests for the artifact_store tool — guards against path traversal."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.artifact_store import ArtifactInput, artifact_store


def test_path_inside_artifacts_dir_passes(tmp_artifact_dir: Path) -> None:
    chart = tmp_artifact_dir / "chart.html"
    chart.write_text("<html></html>")
    with use_node("sandbox_executor"):
        out = artifact_store(
            ArtifactInput(
                run_id=str(uuid4()),
                thread_id=str(uuid4()),
                artifact_type="plotly_html",
                path=str(chart),
            )
        )
    # No session_provider in this test — output urls/ids are empty,
    # but the path validation passed (no exception).
    assert out is not None


def test_path_outside_artifacts_dir_rejected(tmp_artifact_dir: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path.parent / "evil.html"
    elsewhere.write_text("<html></html>")
    with use_node("sandbox_executor"), pytest.raises(ValueError, match="outside ARTIFACTS_DIR"):
        artifact_store(
            ArtifactInput(
                run_id=str(uuid4()),
                thread_id=str(uuid4()),
                artifact_type="plotly_html",
                path=str(elsewhere),
            )
        )


def test_wrong_extension_rejected(tmp_artifact_dir: Path) -> None:
    p = tmp_artifact_dir / "chart.png"
    p.write_text("not html")
    with use_node("sandbox_executor"), pytest.raises(ValueError, match="must be .html"):
        artifact_store(
            ArtifactInput(
                run_id=str(uuid4()),
                thread_id=str(uuid4()),
                artifact_type="plotly_html",
                path=str(p),
            )
        )
