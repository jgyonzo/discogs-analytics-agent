# Discogs Conversational Analytics Agent — V1

Component B per [Constitution Principle VI](../.specify/memory/constitution.md):
a containerized FastAPI + LangGraph service that answers
natural-language analytical questions about the Discogs catalog
by reading the published DuckDB produced by the ETL.

The full design lives in [`specs/004-agent-v1/`](../specs/004-agent-v1/),
extended by [`specs/005-agent-schema-context/`](../specs/005-agent-schema-context/)
(schema-context enrichment + `succeeded_empty` empty-result
guardrail). This README is the operator-facing quickstart; for
the whole runbook see [`specs/004-agent-v1/quickstart.md`](../specs/004-agent-v1/quickstart.md)
and [`specs/005-agent-schema-context/quickstart.md`](../specs/005-agent-schema-context/quickstart.md).

### 005 schema-context enrichment (this branch)

The agent's prompts now receive a pre-rendered schema block that
includes column names + sample distinct values for the low-
cardinality categorical columns (`primary_genre`,
`primary_format_group`, `decade`, `country` top-20,
`release_fact.style` top-50) plus a small domain glossary.
Without this, the LLM had no way to know that "Techno" is a
`style` value (on `release_fact`), not a `primary_genre` value
on `release_unique_view` — so style queries silently returned
zero rows.

A new terminal status `succeeded_empty` covers the case where
SQL runs cleanly but returns no rows: the API surfaces a
"no matching releases" message with the SQL preserved, instead
of shipping a blank chart with `status: succeeded`.

---

## Quickstart

From the repo root:

```bash
# 1. Provide secrets and a DuckDB.
cp .env.example .env
# edit .env to set OPENAI_API_KEY

# Drop your published DuckDB at:
#   ./data/published/duckdb/discogs.duckdb
# (Produce it via the ETL — see ../etl/README.md)

# 2. Bring up the stack (US2).
docker compose up --build

# 3. Wait for health to flip green.
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null
do sleep 2
done
```

`GET /health` reports the DuckDB and Postgres reachability
separately (200 = both ok, 503 = either failing):

```json
{
  "status": "ok",
  "checks": {
    "duckdb":   {"ok": true, "tables_present": ["release_fact","release_unique_view","release_artist_bridge","release_label_bridge","master_fact"], "has_master_fact": true, "error": null, "path": "/app/data/published/duckdb/discogs.duckdb"},
    "postgres": {"ok": true, "error": null}
  },
  "version": "<git sha or 'dev'>",
  "model_provider": "openai"
}
```

`AGENT_VERSION` is a build arg; bake the SHA in via
`AGENT_VERSION=$(git rev-parse --short HEAD) docker compose up --build`.

```bash
# 4. Ask a question (the headline demo — SC-002 anchor).
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' | jq .
```

The response includes a `chart_artifact.url`; open it in a
browser to see the Plotly chart. The chart file lives on the
host at `./artifacts/<thread_id>/<run_id>/<chart>.html`.

### Persistence across restart (SC-009 anchor)

Postgres lives in the named volume `postgres_data` and survives
a stop/start cycle:

```bash
RUN_ID=<paste run_id from the /query response>

docker compose down
docker compose up -d
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null
do sleep 2
done

# (US3) The previously created run is still queryable:
curl -s "http://localhost:8000/runs/$RUN_ID" | jq '.run_id'
```

### Tear down

```bash
docker compose down              # stop containers, keep volumes
docker compose down --volumes    # also drop postgres_data + artifacts
```

---

## Architecture

```text
data/published/duckdb/discogs.duckdb   ← ETL output (read-only)
                ↓ (mounted :ro)
        ┌───────────────┐
        │  agent-api    │  FastAPI + LangGraph
        │   :8000       │     ├── /query
        │               │     ├── /health
        │               │     ├── /artifacts/{id}
        │               │     └── /threads/{id}, /runs/{id}  (US3)
        └──────┬────────┘
               │ trace
               ▼
        ┌───────────────┐
        │  postgres     │  6 agent_* tables
        │   :5432       │
        └───────────────┘
```

LangGraph is a deterministic 8-node graph:

```text
load_schema → router → query_understanding → code_generator
  → sql_safety_checker → sandbox_executor → chart_validator
    → response_synthesizer → END
```

Retry edges loop from `sql_safety_checker` and `chart_validator`
back to `code_generator`, capped at `MAX_RETRIES`.

The compiled graph (rendered straight from
`graph.builder.build_graph().get_graph().draw_mermaid()`) is
checked in at [`docs/graph.mmd`](docs/graph.mmd) — paste it into
any Mermaid renderer (e.g.
[mermaid.live](https://mermaid.live)) for a visual overview.

---

## Running tests

Inside the dev venv (host):

```bash
cd agent
python -m venv .venv && source .venv/bin/activate
pip install -e '.[test,dev]'

# Unit + graph-path tests (LLM-stub, SQLite — no Docker, no key).
pytest tests/unit/ tests/graph/
```

Integration tests pull testcontainers (real Postgres) for the
checks that need it; the rest fall back to file-backed SQLite:

```bash
pytest tests/integration/
```

Set `AGENT_USE_POSTGRES=1` to also run the Postgres variants of
the persistence-durability test (T082).

Docker compose smoke test — gated, builds the image and burns
real OpenAI credit:

```bash
AGENT_DOCKER_SMOKE=1 pytest tests/integration/test_docker_smoke.py
```

Golden tests (LLM-stub by default):

```bash
pytest tests/golden/
```

### Coverage

The Phase 7 baseline (`pytest --cov=discogs_agent`, run against the
default test set — i.e. excluding the docker-compose smoke,
testcontainers Postgres variants, and the sandbox-fsize budget
test which all need extra environment) is:

| Strata | Coverage |
|--------|---------:|
| Total (across `src/discogs_agent/`) | **89 %** |
| Graph nodes (`graph/nodes/*`) | 90–100 % per file |
| Tools (`tools/*`) | 86–100 % per file |
| Persistence (`persistence/*`) | 76–97 % |
| API surface (`api*.py`) | 75–98 % |

The biggest uncovered chunks are the OpenAI-only path in
`llm/client.py` (~41 %, exercised only in the docker smoke test
which burns real credit) and `sandbox/restrictions.py` (~32 %,
the Linux preexec / RLIMIT branches are kernel-platform-specific
and exercised on the agent container, not the macOS host).
Bringing these to 100 % requires running the gated suites:

```bash
AGENT_USE_POSTGRES=1 pytest tests/integration/test_persistence_survives_restart.py
AGENT_DOCKER_SMOKE=1 pytest tests/integration/test_docker_smoke.py
pytest tests/integration/test_sandbox_fsize_budget.py   # Linux only
```

---

## Configuration

All knobs live in `.env` (gitignored). See `.env.example` at the
repo root for the canonical list.

---

## What's NOT in V1

- Frontend UI; AWS deployment; MCP wrappers; RAG; sandbox-worker
  container; auth; multi-tenant security; S3 artifacts.

See [`specs/004-agent-v1/quickstart.md` §12](../specs/004-agent-v1/quickstart.md) for the full deferred list.
