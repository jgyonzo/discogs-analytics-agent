# genai-pathway-final-project-yonzo

A two-component system that turns the public Discogs XML dumps into a
queryable analytics surface, then lets you ask natural-language
questions over it.

- **`etl/`** — local-first batch tool. Streams the monthly Discogs
  `releases.xml` / `masters.xml` / `artists.xml` dumps, materializes
  layered Parquet contracts (`staging` → `clean` → `analytics`), and
  publishes a single DuckDB at
  `data/published/duckdb/discogs.duckdb`.
- **`agent/`** — containerized FastAPI + LangGraph service. Answers
  natural-language questions over the published DuckDB by generating and executing read-only Python/SQL inside a sandbox, then rendering a
  Plotly chart.

The two halves are coupled **only** through the published DuckDB and
the contracts in `specs/001-discogs-etl/contracts/duckdb-schema.md`
and `specs/003-masters-artists/contracts/duckdb-schema.md`. They have
their own dependency manifests, their own test suites, and run
independently. This separation is governed by Principle VI
("Two Components, One Contract") of the project constitution at
[`.specify/memory/constitution.md`](.specify/memory/constitution.md).

---

## Architecture

```text
   Discogs XML dumps                          natural-language question
   (releases / masters / artists)                       │
              │                                         ▼
              ▼                                ┌────────────────────┐
   ┌────────────────────┐                      │   agent (FastAPI   │
   │      etl CLI       │     publishes        │   + LangGraph,     │
   │  python -m         │  ──────────────────▶ │   sandboxed exec)  │
   │  discogs_etl.cli   │   discogs.duckdb     │   :8000            │
   └────────────────────┘    (read-only        └──────┬─────────────┘
              │              contract)                │
              ▼                                       ▼
   data/{staging,clean,                       Plotly chart artifact
   analytics}/{run_id}/                       + run trace in Postgres
```

The agent's LangGraph is a deterministic 8-node pipeline:

```text
load_schema → router → query_understanding → code_generator
  → sql_safety_checker → sandbox_executor → chart_validator
    → response_synthesizer → END
```

with retry edges from `sql_safety_checker` and `chart_validator` back
to `code_generator`, capped at `MAX_RETRIES`. The compiled graph is
checked in at [`agent/docs/graph.mmd`](agent/docs/graph.mmd).

---

## Repository layout

```text
.
├── etl/                  # ETL component (Python CLI, Parquet/DuckDB)
├── agent/                # Agent component (FastAPI + LangGraph + sandbox)
├── specs/                # Spec Kit feature specs (the SDD source of truth)
│   ├── 001-discogs-etl/              # ETL Fase 1 — release_fact baseline
│   ├── 002-etl-scaleup/              # ETL Fase 2+3 — real-data + scale
│   ├── 003-masters-artists/          # ETL Fase 4 — master_fact + artists
│   ├── 004-agent-v1/                 # Agent V1 — graph, API, sandbox, contracts
│   ├── 005-agent-schema-context/     # Schema-context enrichment + empty-result guard
│   ├── 006-bugfix-postmortem/        # Three-bug postmortem → Constitution v1.2.0
│   └── 007-sandbox-fsize-budget/     # Active: raise RLIMIT_FSIZE for DuckDB spill
├── docs/                 # Original design notes (pre-Spec Kit)
├── data/                 # Gitignored runtime data (raw, staging, clean, published…)
├── docker-compose.yml    # agent-api + postgres for the agent stack
├── .specify/             # Spec Kit configuration; constitution lives here
└── CLAUDE.md             # Active-feature pointer for AI assistants
```

`data/` is gitignored except for any small fixtures explicitly added
under `*/tests/fixtures/`.

---

## Quickstart

### 1. Run the ETL once

The ETL produces the DuckDB the agent reads. The repo ships a
7-release curated fixture so you can smoke-test the pipeline without
downloading the real dumps.

```bash
pip install -e 'etl/[test]'

mkdir -p data/raw/discogs/discogs-2026-04
cp etl/tests/fixtures/releases_sample.xml \
   data/raw/discogs/discogs-2026-04/releases.xml
# Optional — masters and artists are auto-detected:
cp etl/tests/fixtures/masters_sample.xml  data/raw/discogs/discogs-2026-04/masters.xml
cp etl/tests/fixtures/artists_sample.xml  data/raw/discogs/discogs-2026-04/artists.xml

python -m discogs_etl.cli run --config etl/configs/base.yml

duckdb data/published/duckdb/discogs.duckdb \
  -c 'SELECT COUNT(DISTINCT release_id) FROM release_fact;'
```

For the full ~19M-release April-2026 dump (≈1 hour CPU on a laptop,
60–120 GB intermediate disk), see
[`etl/README.md`](etl/README.md) §"Running on the full Discogs dump".

### 2. Bring up the agent stack

```bash
cp .env.example .env
# edit .env to set OPENAI_API_KEY

# Drop the published DuckDB at:
#   ./data/published/duckdb/discogs.duckdb
# (produced by step 1 above)

docker compose up --build

until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null
do sleep 2
done
```

### 3. Ask a question

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' | jq .
```

The response includes a `chart_artifact.url`; open it in a browser to
see the Plotly chart. Files land at
`./artifacts/<thread_id>/<run_id>/<chart>.html`.

The full agent runbook (health endpoints, persistence across
restart, admin endpoints, configuration knobs) lives in
[`agent/README.md`](agent/README.md) and
[`specs/004-agent-v1/quickstart.md`](specs/004-agent-v1/quickstart.md).

---

## Development model

The project is governed by a written constitution and developed via
the Spec Kit cycle (`/speckit-specify` → `/speckit-clarify` →
`/speckit-plan` → `/speckit-tasks` → `/speckit-implement`). Every
non-trivial change goes through a feature spec under `specs/`.

- **Constitution** — [`.specify/memory/constitution.md`](.specify/memory/constitution.md)
  (v1.2.0). The constitution prevails on any conflict with this
  README, with `CLAUDE.md`, or with a feature plan.
- **Active feature** — pinned in `.specify/feature.json`. CLAUDE.md
  always points at the currently in-flight feature.
- **AI assistant guidance** — [`CLAUDE.md`](CLAUDE.md) (Claude Code
  reads this as project instructions).

Key correctness disciplines for the agent component (Principle VII,
ratified after the 006 postmortem):

1. **Configuration sources** — model IDs, paths, timeouts, token
   budgets MUST come from `settings` (env via `pydantic-settings`)
   or graph state. No hardcoded literals.
2. **Prompt-authoring discipline** — schema information enters
   prompts only via the dynamically-rendered
   `{schema_context_block}` placeholder; static prose describing
   tables/columns/values is forbidden.
3. **Read-only runtime mechanics** — when something is mounted `:ro`
   or jailed, its consequences must be documented next to the
   constraint (e.g. DuckDB's spill location, RLIMIT side-effects).

---

## Tests

```bash
# ETL — unit + always-on integration (~84 tests, <1s)
pytest etl/tests/

# ETL — gated big-fixture (Fase 3 scale check)
DISCOGS_BIG_FIXTURE=1 pytest etl/tests/integration/test_big_sample_pipeline.py

# Agent — unit + graph-path (no Docker, no key)
cd agent && pytest tests/unit tests/graph

# Agent — integration (testcontainers Postgres for the durability test)
cd agent && AGENT_USE_POSTGRES=1 pytest tests/integration/

# Agent — golden suite (LLM-stub by default)
cd agent && pytest tests/golden/

# Agent — docker-compose smoke (gated, burns OpenAI credit)
cd agent && AGENT_DOCKER_SMOKE=1 pytest tests/integration/test_docker_smoke.py
```

Component-specific test details live in
[`etl/README.md`](etl/README.md) and [`agent/README.md`](agent/README.md).

---

## Out of scope (V1)

- Automated download from Discogs (deferred to a future ETL phase).
- AWS deployment of the agent (containerized service exists; the
  deploy target is undecided).
- Frontend UI; MCP wrappers; RAG; multi-tenant auth.
- `artist_dim` table in DuckDB (`clean_artists.parquet` is produced
  as foundation; surfacing waits on a future spec).
- `release_genre_bridge`, `company_bridge`, and a `master_id` denorm
  on `release_fact` (the last would require a constitution amendment).

See `specs/<feature>/quickstart.md` §"Out of scope" for each
feature's deferred list.
