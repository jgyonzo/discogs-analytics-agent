# Discogs Analytics Agent

A three-component system that turns the public [Discogs](https://www.discogs.com)
XML dumps into a queryable analytics surface, lets you ask natural-language
questions over it, and serves the answers in a browser.

- **`etl/`** — local-first batch tool. Streams the monthly Discogs
  `releases.xml` / `masters.xml` / `artists.xml` dumps, materializes
  layered Parquet contracts (`staging` → `clean` → `analytics`), and
  publishes a single DuckDB at
  `data/published/duckdb/discogs.duckdb`.
- **`agent/`** — containerized FastAPI + LangGraph service. Answers
  natural-language questions over the published DuckDB by generating and executing read-only Python/SQL inside a sandbox, then rendering a
  Plotly chart.
- **`frontend/`** — browser UI (React + Vite + TypeScript). Calls the
  agent's HTTP API and renders the chart artifact + generated SQL +
  data preview + run metadata inline. Runs as a service in
  `docker-compose.yml` alongside the agent. Never touches DuckDB,
  Postgres, or local data files directly.

The components meet at **two contract boundaries, and nowhere else**:

- **`etl` ↔ `agent`** — coupled only through the published DuckDB and the
  contracts in `specs/001-discogs-etl/contracts/duckdb-schema.md` and
  `specs/003-masters-artists/contracts/duckdb-schema.md`. This boundary is
  governed by Principle VI ("Two Components, One Contract") of the project
  constitution at
  [`.specify/memory/constitution.md`](.specify/memory/constitution.md).
- **`frontend` ↔ `agent`** — coupled only through the agent's HTTP API plus a
  single CORS allowance (`http://localhost:5173`). The frontend was added as a
  third component on top of this contract; the matching PATCH amendment to
  Principle VI's prose is tracked as a follow-up.

Each component has its own dependency manifest, its own test suite, and runs
independently.

---

## Architecture

```text
   Discogs XML dumps                          ┌────────────────────┐
   (releases / masters / artists)             │  frontend (React + │
              │                               │  Vite + TS SPA)    │
              ▼                               │  :5173             │
   ┌────────────────────┐                     └─────────┬──────────┘
   │      etl CLI       │     publishes                 │ HTTP /query
   │  python -m         │  ──────────────┐              │ (+ CORS)
   │  discogs_etl.cli   │   discogs.duckdb│              ▼
   └────────────────────┘   (read-only    │   ┌────────────────────┐
              │             contract)      └─▶ │   agent (FastAPI   │
              ▼                                │   + LangGraph,     │
   data/{staging,clean,                       │   sandboxed exec)  │
   analytics}/{run_id}/                       │   :8000            │
                                              └─────────┬──────────┘
                                                        ▼
                                            Plotly chart artifact
                                            + run trace in Postgres
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
├── frontend/             # Frontend component (React + Vite + TypeScript SPA)
├── specs/                # Spec Kit feature specs — one NNN-name dir per feature (SDD source of truth)
├── docs/                 # Original design notes (pre-Spec Kit)
├── data/                 # Gitignored runtime data (raw, staging, clean, published…)
├── docker-compose.yml    # postgres + agent-api + frontend
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

### 3. Ask a question (CLI)

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show the evolution of Techno releases over time"}' | jq .
```

The response includes a `chart_artifact.url`; open it in a browser to
see the Plotly chart. Files land at
`./artifacts/<thread_id>/<run_id>/<chart>.html`.

### 4. Or use the browser frontend

The same `docker compose up --build` from step 2 also brings up the
frontend. Open `http://localhost:5173` in a browser:

- Click a curated demo question (or type your own) → the chart
  renders inline alongside the generated SQL, a tabular data
  preview, and run-metadata badges.
- Multi-turn conversations carry context; "New conversation" resets.
- The frontend never touches DuckDB or local data files; it talks
  only to the agent's HTTP API.

Frontend runbook (component layout, env vars, how to run tests, how
to point at a different agent) lives in
[`frontend/README.md`](frontend/README.md) and
[`specs/008-agent-frontend-v1/quickstart.md`](specs/008-agent-frontend-v1/quickstart.md).

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
- A V1.1 production-shaped frontend image (multi-stage build →
  nginx serving a static bundle). V1 ships the dev-server inside
  the container — see `specs/008-agent-frontend-v1/research.md` §R1.
- MCP wrappers; RAG; multi-tenant auth.
- `artist_dim` table in DuckDB (`clean_artists.parquet` is produced
  as foundation; surfacing waits on a future spec).
- `release_genre_bridge`, `company_bridge`, and a `master_id` denorm
  on `release_fact` (the last would require a constitution amendment).

See `specs/<feature>/quickstart.md` §"Out of scope" for each
feature's deferred list.

---

## License

This project's source code is licensed under the **MIT License** — see
[`LICENSE`](LICENSE).

It bundles sample data derived from the public [Discogs](https://www.discogs.com)
data dumps (released under CC0 1.0) for testing and demonstration. That
third-party data is **not** covered by the MIT License above; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for details and attribution.
