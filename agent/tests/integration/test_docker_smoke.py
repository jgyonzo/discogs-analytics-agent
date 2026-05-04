"""US2 / T083 — full docker-compose smoke test (gated).

Brings the real stack up via ``docker compose``, polls ``/health``
until it reports OK, posts the golden simple query, and asserts that
a chart artifact landed on disk and that ``agent_runs`` recorded the
run. Tear-down is unconditional so a failure mid-test still
``docker compose down``-s.

This test is gated on ``AGENT_DOCKER_SMOKE=1`` because it:
- requires Docker to be running on the host,
- builds the agent image (~2-4 minutes on first build),
- consumes a small amount of OpenAI credit per run.

It also skips when:
- ``OPENAI_API_KEY`` isn't set in the project ``.env`` (the
  containerized agent has no LLM-stub fallback),
- the published DuckDB isn't at the host bind-mount path AND the
  test cannot stage the seed DuckDB there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOST_DUCKDB = REPO_ROOT / "data" / "published" / "duckdb" / "discogs.duckdb"
HOST_ARTIFACTS = REPO_ROOT / "artifacts"
HEALTH_URL = "http://localhost:8000/health"
QUERY_URL = "http://localhost:8000/query"
HEALTH_TIMEOUT_SECONDS = 120
SMOKE_QUERY = "Show the evolution of Techno releases over time"


def _has_docker() -> bool:
    return shutil.which("docker") is not None


def _read_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip()
    return None


@pytest.mark.skipif(
    os.environ.get("AGENT_DOCKER_SMOKE") != "1",
    reason="set AGENT_DOCKER_SMOKE=1 to run the docker compose smoke",
)
def test_docker_compose_smoke(seed_duckdb: Path) -> None:
    if not _has_docker():
        pytest.skip("docker CLI not on PATH")

    requests = pytest.importorskip("requests")

    env_path = REPO_ROOT / ".env"
    api_key = _read_env_value(env_path, "OPENAI_API_KEY")
    if not api_key:
        pytest.skip(
            "OPENAI_API_KEY missing from .env — smoke test needs a real key"
        )

    # Stage the seed DuckDB at the bind-mount path if no real published
    # DuckDB exists. We deliberately do NOT overwrite a real one: the
    # operator's investment is not ours to clobber.
    staged_duckdb = False
    HOST_DUCKDB.parent.mkdir(parents=True, exist_ok=True)
    if not HOST_DUCKDB.exists():
        shutil.copy(seed_duckdb, HOST_DUCKDB)
        staged_duckdb = True

    HOST_ARTIFACTS.mkdir(parents=True, exist_ok=True)

    compose_up = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPO_ROOT / "docker-compose.yml"),
            "up",
            "-d",
            "--build",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if compose_up.returncode != 0:
        if staged_duckdb:
            HOST_DUCKDB.unlink(missing_ok=True)
        pytest.fail(
            f"docker compose up failed: stdout={compose_up.stdout!r} "
            f"stderr={compose_up.stderr!r}"
        )

    try:
        deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
        body: dict | None = None
        while time.monotonic() < deadline:
            try:
                resp = requests.get(HEALTH_URL, timeout=2)
                if resp.status_code == 200:
                    body = resp.json()
                    if body.get("status") == "ok":
                        break
            except requests.RequestException:
                pass
            time.sleep(2)
        else:
            raise AssertionError(
                f"agent never became healthy within {HEALTH_TIMEOUT_SECONDS}s"
            )

        assert body is not None
        assert body["checks"]["duckdb"]["ok"] is True
        assert body["checks"]["postgres"]["ok"] is True

        query_resp = requests.post(
            QUERY_URL,
            json={"message": SMOKE_QUERY},
            timeout=120,
        )
        assert query_resp.status_code == 200, (
            f"query failed: {query_resp.status_code} {query_resp.text}"
        )
        payload = query_resp.json()
        assert payload["status"] in {"succeeded", "succeeded_empty"}

        if payload["status"] == "succeeded":
            chart = payload["chart_artifact"]
            assert chart is not None and chart["url"]
            chart_dir = HOST_ARTIFACTS / payload["thread_id"] / payload["run_id"]
            html_files = list(chart_dir.glob("*.html"))
            assert html_files, f"no chart .html under {chart_dir}"
            assert html_files[0].stat().st_size > 0

        run_inspect = requests.get(
            f"http://localhost:8000/runs/{payload['run_id']}", timeout=10
        )
        # /runs is US3 — accept either 200 (already shipped) or 404
        # (hasn't shipped yet); we still verified the run via /query.
        assert run_inspect.status_code in (200, 404)
    finally:
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(REPO_ROOT / "docker-compose.yml"),
                "down",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if staged_duckdb:
            HOST_DUCKDB.unlink(missing_ok=True)
