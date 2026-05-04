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

# 2. Bring up the stack.
docker compose up --build

# 3. Wait for health to flip green.
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null
do sleep 2
done

# 4. Ask a question.
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' | jq .
```

The response includes a `chart_artifact.url`; open it in a
browser to see the Plotly chart.

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

Integration tests need testcontainers (real Postgres):

```bash
AGENT_USE_POSTGRES=1 pytest tests/integration/
```

Golden tests (LLM-stub by default):

```bash
pytest tests/golden/
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
