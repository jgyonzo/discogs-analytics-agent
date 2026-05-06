"""Tests for the sandbox runner + sandbox_executor tool."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from discogs_agent.observability.tracing import use_node
from discogs_agent.sandbox.runner import run_in_sandbox


def test_sandbox_clean_success(tmp_path: Path, seed_duckdb: Path) -> None:
    code = '''import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path
import os

DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]
ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(DB_PATH, read_only=True)

sql = """SELECT decade, COUNT(*) AS releases FROM release_unique_view GROUP BY decade ORDER BY decade"""
df = con.execute(sql).df()
fig = px.bar(df, x="decade", y="releases", title="t")
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")
RESULT = {"sql": sql, "chart_path": str(chart_path), "dataframe_preview": df.head(20).to_dict(orient="records"), "row_count": len(df), "chart_type": "bar"}
'''
    outcome = run_in_sandbox(
        generated_code=code,
        thread_id=str(uuid4()),
        run_id=str(uuid4()),
        timeout_seconds=30,
        duckdb_path=str(seed_duckdb),
        artifacts_root=str(tmp_path),
    )
    assert outcome.exit_code == 0, f"stderr={outcome.stderr}"
    assert outcome.exception_type is None
    assert outcome.result is not None
    assert outcome.result["row_count"] > 0
    assert outcome.result["chart_path"].endswith(".html")
    assert Path(outcome.result["chart_path"]).exists()


def test_sandbox_timeout(tmp_path: Path, seed_duckdb: Path) -> None:
    code = "import time\ntime.sleep(60)\nRESULT = {}\n"
    outcome = run_in_sandbox(
        generated_code=code,
        thread_id=str(uuid4()),
        run_id=str(uuid4()),
        timeout_seconds=2,
        duckdb_path=str(seed_duckdb),
        artifacts_root=str(tmp_path),
    )
    assert outcome.exception_type == "timeout"
    assert outcome.result is None


def test_sandbox_no_secret_leak(
    tmp_path: Path, seed_duckdb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPENAI_API_KEY / DATABASE_URL set in the parent must NOT be
    visible to the subprocess."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-test-12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-appear")

    code = """import os
import json
keys = ["OPENAI_API_KEY", "DATABASE_URL", "AWS_SECRET_ACCESS_KEY"]
RESULT = {"sql": "", "chart_path": "/tmp/x.html", "dataframe_preview": [], "row_count": 0, "chart_type": "bar", "_present_keys": [k for k in keys if k in os.environ]}
"""
    outcome = run_in_sandbox(
        generated_code=code,
        thread_id=str(uuid4()),
        run_id=str(uuid4()),
        timeout_seconds=10,
        duckdb_path=str(seed_duckdb),
        artifacts_root=str(tmp_path),
    )
    # The subprocess will fail validation later (chart_path outside
    # ARTIFACT_DIR); but we only care here about its env contents.
    assert outcome.result is not None
    assert outcome.result["_present_keys"] == [], (
        f"secret env vars leaked into sandbox: {outcome.result['_present_keys']}"
    )


def test_sandbox_no_pkg_install(tmp_path: Path, seed_duckdb: Path) -> None:
    """pip is not on the cleaned PATH; subprocess shelling out fails."""
    code = """import subprocess
result = subprocess.run(["pip", "install", "nonexistent-package-xyz"], capture_output=True, text=True)
RESULT = {"sql": "", "chart_path": "/tmp/x.html", "dataframe_preview": [], "row_count": result.returncode, "chart_type": "bar"}
"""
    outcome = run_in_sandbox(
        generated_code=code,
        thread_id=str(uuid4()),
        run_id=str(uuid4()),
        timeout_seconds=10,
        duckdb_path=str(seed_duckdb),
        artifacts_root=str(tmp_path),
    )
    # Either subprocess returns nonzero (pip not found / install failed)
    # or the script raises. Either way the sandbox didn't install the
    # package successfully.
    if outcome.result is not None:
        assert outcome.result["row_count"] != 0


def test_sandbox_runs_seed_query(tmp_path: Path, seed_duckdb: Path) -> None:
    """End-to-end: sandbox can read the seed DuckDB and produce a chart."""
    from discogs_agent.config import settings
    from discogs_agent.tools.sandbox_executor import SandboxInput, sandbox_executor

    settings.ANALYTICS_DUCKDB_PATH = str(seed_duckdb)
    settings.ARTIFACTS_DIR = str(tmp_path)

    code = """import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path
import os

DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]
ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(DB_PATH, read_only=True)
sql = "SELECT decade, COUNT(*) AS releases FROM release_unique_view GROUP BY decade ORDER BY decade"
df = con.execute(sql).df()
fig = px.bar(df, x="decade", y="releases", title="t")
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")
RESULT = {"sql": sql, "chart_path": str(chart_path), "dataframe_preview": df.head(20).to_dict(orient="records"), "row_count": len(df), "chart_type": "bar"}
"""
    thread_id = str(uuid4())
    run_id = str(uuid4())
    with use_node("sandbox_executor"):
        out = sandbox_executor(
            SandboxInput(
                generated_code=code,
                thread_id=thread_id,
                run_id=run_id,
                timeout_seconds=30,
            )
        )
    assert out.exit_code == 0
    assert out.result is not None
    assert out.result["chart_type"] == "bar"
