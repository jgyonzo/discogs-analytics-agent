# Quickstart: Discogs Conversational Analytics Agent — V1

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Audience**: a developer / reviewer / demo evaluator standing up
the agent for the first time on a clean checkout.

This walkthrough assumes the implementation tasks (produced by
`/speckit-tasks` in the next phase) are complete. It doubles as
the manual integration script for SC-001 (15-minute time-to-chart
from a clean checkout).

---

## 0. Prerequisites

- macOS or Linux. Windows not validated.
- Docker (Engine ≥ 24, or Docker Desktop) running.
- Python 3.12+ on the host (only needed for the optional CLI;
  the API runs in the container).
- Disk: ≥ 2 GiB free for the image build + Postgres volume.
- A published DuckDB at
  `data/published/duckdb/discogs.duckdb` — produced by an
  earlier ETL run conforming to specs 001/002/003. The
  smallest acceptable input is the curated tiny snapshot from
  [`specs/003-masters-artists/quickstart.md` §2](../003-masters-artists/quickstart.md);
  the demo target is the real April 2026 dump.
- An OpenAI API key with access to `gpt-4o-mini` and `gpt-4o`.

---

## 1. Configure secrets

From the repo root:

```bash
cp .env.example .env
```

Edit `.env` to set:

```text
OPENAI_API_KEY=sk-...
# everything else has working defaults; override only if you need to.
```

The full env reference is in
[`research.md` R-13](./research.md). The defaults that
matter:

```text
ANALYTICS_DUCKDB_PATH = /app/data/published/duckdb/discogs.duckdb
DATABASE_URL          = postgresql+psycopg://agent:agent@postgres:5432/agent
ARTIFACTS_DIR         = /app/artifacts
CHEAP_MODEL           = gpt-4o-mini
STRONG_MODEL          = gpt-4o
MAX_RETRIES           = 2
SANDBOX_TIMEOUT_SECONDS = 30
THREAD_CARRYOVER_TURNS  = 4
THREAD_CARRYOVER_TOKEN_BUDGET = 512
```

`.env` is gitignored at the repo root. Never commit it
(Constitution: Secrets).

---

## 2. Bring up the stack

From the repo root:

```bash
docker compose up --build
```

First boot builds the agent image (~2–4 min depending on
network) and pulls Postgres. Subsequent boots are fast.

In a separate terminal, poll `/health` until OK:

```bash
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null
do sleep 2
done
echo "agent is ready"
```

Expected health body:

```json
{
  "status": "ok",
  "checks": {
    "duckdb":   { "ok": true,  "tables_present": ["release_fact","release_unique_view","release_artist_bridge","release_label_bridge","master_fact"], "has_master_fact": true, "error": null, "path": "/app/data/published/duckdb/discogs.duckdb" },
    "postgres": { "ok": true,  "error": null }
  },
  "version": "<git sha>",
  "model_provider": "openai"
}
```

If `status = "unavailable"`, see §7 troubleshooting.

---

## 3. Send the golden query

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' | jq .
```

Expected (success):

```json
{
  "thread_id": "9f6c...e1",
  "run_id": "1a2b...c3",
  "response": "Generated a line chart of Techno releases per year, peaking around <year>.",
  "route": {
    "complexity": "simple",
    "selected_model": "gpt-4o-mini",
    "rationale": "..."
  },
  "sql": "SELECT year, COUNT(DISTINCT release_id) AS releases\nFROM release_fact\nWHERE style = 'Techno'\n  AND year IS NOT NULL\nGROUP BY year\nORDER BY year",
  "code": null,
  "chart_artifact": {
    "artifact_id": "7d3e...f8",
    "url": "/artifacts/7d3e...f8",
    "type": "plotly_html"
  },
  "dataframe_preview": [...],
  "row_count": 35,
  "status": "succeeded",
  "carryover": {"turn_count": 0, "preamble": null}
}
```

Open the chart in a browser:

```bash
open "http://localhost:8000/artifacts/<artifact_id>"
```

(or `xdg-open` on Linux).

---

## 4. Continue the conversation

Reuse the `thread_id` from §3 to ask a follow-up:

```bash
THREAD_ID=<paste from §3>

curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d "{\"thread_id\": \"$THREAD_ID\", \"message\": \"Now compare that to House.\"}" | jq .
```

Expected: the new run is grouped under the same thread, and
the carry-over preamble shows up:

```json
{
  ...
  "carryover": {
    "turn_count": 1,
    "preamble": "Recent conversation:\n- Show the evolution of Techno releases over time"
  },
  "sql": "SELECT year, style, COUNT(DISTINCT release_id) AS releases\nFROM release_fact\nWHERE style IN ('Techno', 'House')...",
  ...
}
```

`GET /threads/{THREAD_ID}` lists both runs:

```bash
curl -s "http://localhost:8000/threads/$THREAD_ID" | jq .
```

---

## 5. Inspect a run's full trace

```bash
RUN_ID=<paste from §3 or §4>

curl -s "http://localhost:8000/runs/$RUN_ID" | jq .
```

Expected: route, generated SQL, the tool-call timeline, the
model-usage rows (one per LLM call), the artifact reference,
and the final response. **Generated Python code is NOT
included** unless you set the admin header (the development
default leaves admin disabled — `AGENT_ADMIN_TOKEN=""` in
`.env`). See [`contracts/api.md` §3](./contracts/api.md) for
the admin flow.

---

## 6. Exercise the controlled-failure paths

These are part of SC-003 — controlled responses on the four
negative paths.

### 6.1 Unsupported question

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is the average price of Techno releases?"}' | jq '.status, .response'
```

Expected: `status = "failed_unsupported"`; the response names
*price* as missing and lists what's available.

### 6.2 Clarification-needed question

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show me the best labels."}' | jq '.status, .response'
```

Expected: `status = "failed_clarification_needed"`; the
response asks "best by what metric?" and lists candidates
(release count, distinct styles, distinct artists).

### 6.3 Safety-block path (synthetic; needs the LLM stub)

This one isn't easily triggered by user input — the model
generally avoids forbidden patterns when prompted. To
exercise it, run the integration suite:

```bash
docker compose exec agent-api pytest tests/graph/test_path_safety_retry.py
```

### 6.4 Sandbox failure

Run:

```bash
docker compose exec agent-api pytest tests/graph/test_path_validation_retry.py tests/graph/test_path_retries_exhausted.py
```

---

## 7. Persistence across restart

```bash
docker compose down                 # stops the containers
docker compose up -d                # restarts (volumes persist)
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null; do sleep 2; done

curl -s "http://localhost:8000/runs/$RUN_ID" | jq '.run_id'    # still there
```

Expected: the same `run_id` you submitted in §3 is still
queryable. Postgres volume (`postgres_data`) and the
`./artifacts` bind mount both survived.

---

## 8. Run the test suite

From the repo root, with the stack running:

```bash
docker compose exec agent-api pytest tests/unit/ tests/graph/
```

Unit and graph-path tests use the LLM stub (no OpenAI
calls) and the in-memory SQLite (no testcontainers). Should
finish in under 30 s.

Integration tests (Postgres via testcontainers; DuckDB via
the seed fixture):

```bash
docker compose exec agent-api pytest tests/integration/
```

Golden tests (LLM-stub mode is the default; **set
`AGENT_OPENAI_LIVE=1` only if you want real OpenAI calls and
have a key burning a hole in your wallet**):

```bash
docker compose exec agent-api pytest tests/golden/
# or, for the live demo run:
AGENT_OPENAI_LIVE=1 docker compose exec agent-api pytest tests/golden/
```

Docker smoke (gated):

```bash
AGENT_DOCKER_SMOKE=1 pytest agent/tests/integration/test_docker_smoke.py
```

---

## 9. The agent's golden queries (matches SC-002)

The six documented golden questions:

1. **Releases by decade** — uses `release_unique_view`,
   simple bar.
2. **Techno over time** — uses `release_fact` with
   `COUNT(DISTINCT release_id)`, line.
3. **Vinyl vs CD by decade** — uses `release_unique_view`
   `has_vinyl` / `has_cd`, grouped bar.
4. **Label style diversity** — joins
   `release_label_bridge ⋈ release_fact`, top-N bar.
5. **House outlier years** — CTE with z-score, scatter or
   bar.
6. **Works with most versions** — uses `master_fact`
   (only when `has_master_fact == true`), bar.

Each has a corresponding `tests/golden/test_golden_*.py`
asserting on the persisted SQL shape. The "Techno over time"
one is the SC-008 anchor: its persisted SQL MUST contain
`COUNT(DISTINCT release_id)` or query
`release_unique_view`.

---

## 10. Tear down

```bash
docker compose down                 # keep volumes
# or
docker compose down -v              # also drop postgres_data + artifacts
```

`./artifacts/` accumulates HTML files indefinitely in V1 (no
retention policy). The directory is bind-mounted from the
host, so you can clean it manually:

```bash
rm -rf artifacts/
```

The published DuckDB is **never** modified. Verify (SC-007):

```bash
shasum -a 256 data/published/duckdb/discogs.duckdb
```

before and after a batch of `/query` calls — the hashes match.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/health` returns `duckdb.ok = false` with "no such file" | DuckDB missing | Produce one via the ETL or copy in your existing one. |
| `/health` returns `duckdb.ok = false` with "missing core table" | DuckDB came from an older ETL | Re-run the ETL on this branch (specs 001–003). |
| `/health` returns `postgres.ok = false` | Postgres not up yet | `docker compose logs postgres` — wait for "ready to accept connections". |
| `/query` returns 503 `duckdb_unavailable` | Same as `/health` showing it | See above. |
| `/query` returns 500 `internal_error` | Unexpected exception | `docker compose exec agent-api alembic current` (migrations applied?); check `docker compose logs agent-api`; the run row in `agent_errors` will have the traceback. |
| Chart appears but is empty | Genuinely empty result for the filter | Check `dataframe_preview` is `[]` and `row_count = 0` — it's a documented empty-result case (FR-019). |
| Chart fails to validate ("chart_path outside ARTIFACT_DIR") | Generated code wrote to a hardcoded `/tmp` | The repair prompt should fix it; check `agent_runs.metadata.retry_count`. |

---

## 12. What's NOT in this spec

If any of the below doesn't yet work, that's **by design** —
deferred to follow-up specs:

- **Frontend UI** — V1 is API-only.
- **AWS deployment** — V1 is local-only.
- **MCP wrappers** — V1 tools are local Python.
- **RAG over docs / examples** — schema context is direct
  prompt injection in V1.
- **Sandbox-worker container** — V1 uses an in-host
  subprocess (R-02).
- **Auth on the API** — V1 is unauthenticated.
- **S3 artifact storage** — V1 stores HTML on the host
  bind-mount.
- **Artifact retention policy** — V1 keeps everything.
- **Provider-agnostic LLM abstraction** — V1 is OpenAI-only.
- **Full multi-turn replanning** — V1 is light contextual
  carry-over (text-only).
