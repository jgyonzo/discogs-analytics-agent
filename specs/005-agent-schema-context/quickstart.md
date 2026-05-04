# Quickstart: Agent Schema Context Enrichment

End-to-end verification — no AWS, no production API key.

## Prerequisites

- Local agent venv at `agent/.venv/` with the project deps
  (`uv sync` or `pip install -e agent/`).
- Local Postgres + agent stack running via Docker Compose
  (`agent/README.md` lines 30–32 are the canonical health
  check).
- Published DuckDB at `data/published/duckdb/discogs.duckdb`
  (April 2026 full-dump or a sample DB; the bug surfaces
  against any catalog with both `primary_genre` and `style`).

## 0. Pre-fix baseline (expected to fail)

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' | jq .
```

Pre-fix, the response has `row_count: 0`, `dataframe_preview: []`,
`status: "succeeded"` (which is the bug — should be
`succeeded_empty` once the empty-result handling is in, OR
`succeeded` with non-empty data once the schema-context fix
is in).

## 1. Apply the migration

```bash
cd agent
.venv/bin/python -m alembic -c src/discogs_agent/persistence/alembic.ini upgrade head
```

Confirms the new `005_xx_add_succeeded_empty` migration is
applied. `agent_runs.status` CHECK now includes
`succeeded_empty`.

## 2. Run the unit and integration tests

```bash
cd agent
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/integration -q
```

All 45 prior unit tests still pass; the new ones pass too.

## 3. Run the golden style suite

```bash
cd agent
.venv/bin/python -m pytest tests/golden/test_canonical_styles.py -v
```

Assert: 10/10 canonical style queries return non-empty data
(SC-001).

## 4. Live smoke against Docker Compose

```bash
# Restart the API container so it loads the enriched schema context
docker compose up -d --build agent-api

# Wait for health
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' \
  > /dev/null; do sleep 2; done

# The query that motivated this feature
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' \
  | jq '{status, row_count, sql: .sql}'
```

Expected: `status: "succeeded"`, `row_count: 6` (one row per
decade with Techno releases — 1970s through 2020s), and the
SQL filters `WHERE style = 'Techno'` on `release_fact`,
grouped by `decade`.

```bash
# Empty-result path
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show Polka releases over time"}' \
  | jq '{status, row_count, response}'
```

Expected: `status: "succeeded_empty"`, `row_count: 0`, and the
`response` text contains "no matching releases".

## 5. Inspect the schema context (optional)

```bash
cd agent
.venv/bin/python - <<'PY'
from discogs_agent.duckdb_layer.schema import read_schema_context
import os
ctx = read_schema_context(os.environ["ANALYTICS_DUCKDB_PATH"])
print("token_count:", ctx["rendered_token_count"])
print("primary_genre values:", [
    s["value"] for s in
    ctx["sample_values"]["release_unique_view"]["primary_genre"]
])
print("top-10 styles:", [
    s["value"] for s in
    ctx["sample_values"]["release_fact"]["style"][:10]
])
PY
```

Expected: token count under 600; 14 primary_genre values;
top-10 styles include House, Techno, Ambient, Pop Rock, etc.

## 6. Rollback (if needed)

```bash
cd agent
.venv/bin/python -m alembic -c src/discogs_agent/persistence/alembic.ini downgrade -1
```

The schema-context enrichment is purely in-process; no
rollback is needed for the agent code itself — restart the
container with the previous image. The migration's `downgrade`
restores the original CHECK constraint (no rows are lost since
no production data has used `succeeded_empty` yet).
