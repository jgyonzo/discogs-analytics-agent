# Implementation Plan: Discogs Conversational Analytics Agent — V1

**Branch**: `004-agent-v1` | **Date**: 2026-04-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/004-agent-v1/spec.md`
**Components touched**: `agent/` only (per Constitution Principle VI). Zero edits to `etl/`. The published DuckDB at `data/published/duckdb/discogs.duckdb` is the only contact surface.
**Constitution version**: 1.1.0
**Builds on**: `specs/001-discogs-etl/`, `specs/002-etl-scaleup/`, `specs/003-masters-artists/` (all merged) — for the **published DuckDB contract** only. The agent does not import ETL code or read any non-published artifact.

## Summary

This is the first feature for the second component of the
monorepo. It builds the V1 conversational analytics agent: a
Dockerized FastAPI service that orchestrates a **deterministic
LangGraph StateGraph** to answer natural-language analytical
questions about Discogs by generating Python+SQL, executing it
in a restricted subprocess sandbox, and returning a Plotly HTML
chart artifact. Every run is fully traced and persisted to a
sibling Postgres container. The whole stack boots locally with
`docker compose up --build`.

Three design lines define the work:

1. **A new top-level `agent/` directory** with its own
   `pyproject.toml`, `Dockerfile`, source tree, tests, and
   `docker-compose.yml`. The agent imports nothing from
   `etl/` (Constitution VI).
2. **A deterministic 8-node LangGraph** —
   `load_schema → router → query_understanding → code_generator
   → sql_safety_checker → sandbox_executor → chart_validator
   → response_synthesizer` — with explicit retry edges from
   safety and validation back to code generation, capped by a
   configurable retry budget (default 2).
3. **A two-store persistence model**: Postgres holds the
   relational trace (`agent_threads`, `agent_runs`,
   `agent_tool_calls`, `agent_model_usage`, `agent_artifacts`,
   `agent_errors`); the local filesystem under
   `artifacts/{thread_id}/{run_id}/` holds the chart HTML
   files. Both volumes are durable across `docker compose
   down/up`.

Two scope decisions came from the spec's clarifications and
shape the plan:

- **Provider = OpenAI** (cheap = `gpt-4o-mini`, strong =
  `gpt-4o`), via the `openai` Python SDK wrapped by
  `langchain-openai` for LangGraph integration. Cost
  estimation uses a small in-repo rate card.
- **Multi-turn = light contextual carry-over**: `query_understanding`
  receives the prior runs' *user-query text* (only) summarized
  under a documented turns/token cap. No SQL or generated code
  is carried over.

Out of scope for V1 (per spec non-goals): frontend UI, AWS
deployment, RAG, MCP servers, sandbox-worker container, auth,
multi-tenant security, ETL execution from the agent.

## Technical Context

**Language/Version**: Python 3.12 (matches the ETL component for
developer-tooling consistency, even though there is no
cross-component import).

**Primary Dependencies**:

- **Web/API**: `fastapi`, `uvicorn[standard]`,
  `pydantic` v2 (DTOs).
- **Orchestration**: `langgraph`, `langchain-core`,
  `langchain-openai`. LangGraph is used purely as a
  `StateGraph` builder; no LangGraph checkpointer in V1
  (we persist via our own Postgres tables — see R-05).
- **LLM SDK**: `openai` (transitively pulled by
  `langchain-openai`).
- **Database (Postgres)**: `sqlalchemy` v2 + `psycopg[binary]`
  + `alembic` (for migrations). Sync engine in V1 (FastAPI
  endpoints can `run_in_threadpool` the Postgres calls if
  needed).
- **Database (DuckDB, read-only)**: `duckdb` (same package the
  ETL uses; `read_only=True` is the load-bearing bit).
- **Charting**: `plotly` (`plotly.express` for routine charts,
  `plotly.graph_objects` available for the generator if
  needed). HTML is rendered self-contained via
  `fig.write_html(..., include_plotlyjs="inline")`.
- **Token counting**: `tiktoken` (for OpenAI prompt/completion
  token accounting when a fast pre-call estimate is needed; the
  authoritative counts come from the OpenAI response usage
  block).
- **Logging**: `structlog` (JSON logs), routed through stdlib
  logging so uvicorn / SQLAlchemy log lines stay coherent.
- **Testing**: `pytest`, `pytest-asyncio`, `httpx` (FastAPI
  TestClient via `httpx.ASGITransport`),
  `testcontainers[postgres]` for integration tests against a
  real Postgres (gated; falls back to a developer-supplied
  `TEST_DATABASE_URL` if the runner can't spin Docker).
- **Code quality**: `ruff` for lint, `mypy` strict on the
  `discogs_agent` package, `pytest-cov`.

**Storage**:

- **Postgres** (sibling container) — operational/trace store.
  Schema migrations under `agent/src/discogs_agent/persistence/migrations/`.
  Volume: `postgres_data` (named volume, persists across
  restarts).
- **DuckDB** (read-only mount) — the published analytics surface
  produced by the ETL. Bind-mount `./data/published/duckdb`
  into the container as `/app/data/published/duckdb` with `:ro`.
- **Artifacts** (read-write bind mount) — `./artifacts` →
  `/app/artifacts`. One subdirectory per run:
  `{thread_id}/{run_id}/chart.html`. The agent owns this
  directory; the ETL never writes to it.

**Testing**:

- **Unit** — tools (`dataset_schema_reader`, `query_classifier`,
  `sql_safety_checker`, `sandbox_executor`, `chart_validator`,
  `cost_logger`, `artifact_store`); graph nodes in isolation;
  prompt templating; SQL parser/extractor.
- **Graph path** — every transition combination in the
  `StateGraph` exercised at least once
  (supported-simple, supported-complex, unsupported,
  clarification-needed, safety-retry-then-success,
  validation-retry-then-success, retries-exhausted-controlled-failure).
  Uses an LLM **stub** (deterministic responses keyed by
  query string) so these tests don't require an
  `OPENAI_API_KEY`.
- **Integration** — `agent_simple_query`, `agent_complex_query`,
  `agent_unsupported_query`, `agent_safety_block`,
  `agent_sandbox_failure`, `agent_resume_thread`,
  `duckdb_contract`. Uses a tiny seed DuckDB committed at
  `agent/tests/fixtures/seed.duckdb` (built from a small
  Python script kept under the same path so it's
  reproducible). Postgres via `testcontainers` (gated by an
  env var; falls back to skip when Docker unavailable).
- **Docker smoke** — a single test that boots the full
  `docker-compose.yml`, polls `/health` until OK, posts
  one golden query, asserts a chart artifact lands on disk
  and a row appears in `agent_runs`. Gated by
  `AGENT_DOCKER_SMOKE=1`.
- **Golden queries** — six documented natural-language
  questions (the five-plus-one from the canonical doc
  Section 20). Asserted against persisted SQL using
  pattern-style assertions (e.g., the "Techno over time"
  golden must use `COUNT(DISTINCT release_id)` and `style =
  'Techno'`). LLM stub at the unit/graph layer; **real
  OpenAI calls only on the manually-triggered**
  `AGENT_OPENAI_LIVE=1` end-to-end suite.

**Target Platform**: Linux container (Python 3.12-slim base) for
the API service. Local development on macOS/Linux via Docker
Desktop / Docker Engine. AWS deployment is explicit future
work.

**Project Type**: containerized web service (`agent/` top-level
directory under the existing monorepo).

**Performance Goals**:

- **P50 wall-clock for a simple query** (warm stack, seed
  DuckDB): < 30 s end-to-end (matches SC-010). Bottleneck is
  LLM round-trips; everything else (subprocess boot, DuckDB
  query, Plotly render) is under 1 s for the seed dataset.
- **Sandbox hard timeout**: 30 s (default; configurable via
  `SANDBOX_TIMEOUT_SECONDS`). Subprocess gets killed after
  that.
- **API memory budget**: < 512 MiB per container at idle;
  spikes at code generation are LLM-bounded.

**Constraints**:

- The agent MUST NOT modify the published DuckDB. Verified by
  a byte-equality check before/after a documented integration
  run (SC-007).
- The agent MUST NOT read raw XML / staging Parquet / clean
  Parquet at query time (FR-010 / Constitution VI). Verified
  by allowlist enforcement and by the absence of those paths
  in the container's volume mounts (only the published DuckDB
  is mounted).
- `release_fact` count rule (FR-012 / SC-008) is enforced both
  at the prompt level (every code-generator prompt includes
  the rule) and at the test level (the "Techno over time"
  golden asserts on the persisted SQL).
- Forbidden SQL never executes — the safety checker runs
  *before* `sandbox_executor` and the sandbox does not have a
  fallback path that bypasses it (FR-013 / FR-014). Tested by
  injecting a known-bad generated SQL and asserting the
  safety check blocks before any DuckDB connection opens.
- API responses MUST NOT leak raw tracebacks (FR-024). The
  response synthesizer's prompt explicitly forbids this; an
  integration test asserts `traceback` and `Traceback` strings
  are absent from `/query` responses on a deliberate sandbox
  failure.
- Secrets (FR-031): `.env` is gitignored at the repo root; the
  agent's Docker Compose reads from `.env`. The container
  itself never bakes in `OPENAI_API_KEY` at build time.
- Component independence (FR-033): an `agent/`-only test
  (`test_no_etl_imports.py`) statically asserts that no module
  under `agent/src/discogs_agent/` imports from `discogs_etl.*`.

**Scale/Scope**:

- One developer. One agent container, one Postgres container.
- Single concurrent run per thread (FR-032 edge case).
  Concurrent runs across different threads are fine; FastAPI's
  default worker model is sufficient.
- Demo dataset: the seed DuckDB fixture (~5–20 rows per
  table, hand-built Python seed script) drives unit and
  integration tests; the **real** April 2026 ETL output
  (~19 M release-styles in `release_fact`) is what the
  reviewer points at for the live demo.

## Constitution Check

*Gate: must pass before Phase 0; re-checked at end of Phase 1.*

**Components-touched declaration**: `agent/` only. No edits to
`etl/`; no imports from `discogs_etl.*`. Statically enforced by
`test_no_etl_imports.py`.

| # | Principle | Engaged? | How this plan complies |
|---|-----------|----------|------------------------|
| I | Layered, contract-first data architecture | Indirect (consumer side) | The agent reads only the *published* layer of the ETL contract. The published layer's contract is documented in `specs/001-discogs-etl/contracts/duckdb-schema.md` (release-side) and `specs/003-masters-artists/contracts/duckdb-schema.md` (master_fact). The agent's allowlist (`release_fact`, `release_unique_view`, `release_artist_bridge`, `release_label_bridge`, optional `master_fact`) matches that contract exactly. The agent never reaches across into `stg_*` / `clean_*` / `release_format_summary`. |
| II | Streaming, bounded-memory processing | N/A | The agent does not parse XML and does not produce Parquet. It runs analytical SQL whose result is bounded by the user's `LIMIT` / aggregation. The dataframe preview is capped at 20 rows (canonical doc Section 13). |
| III | Reproducible runs with manifest & logs (NON-NEGOTIABLE) | Yes (analog) | The ETL's "manifest per run" pattern translates here as "a Postgres `agent_runs` row plus per-run `agent_tool_calls` / `agent_model_usage` / `agent_artifacts` / `agent_errors` rows", inspectable via `GET /runs/{run_id}`. Every run gets a UUID `run_id`. Re-running the same query against the same DuckDB and the same model versions produces a logically equivalent run (the LLM is non-deterministic; the *trace structure* is reproducible). |
| IV | Data quality gates | N/A on the producer side; **mirrored** on the consumer side as the SQL safety contract and the chart validator | The ETL's DQ checks remain authoritative for the data itself; the agent's "DQ-equivalent" is the SQL safety contract (FR-013 / FR-014) plus the chart validator (FR-019). Both are non-negotiable: violations fail the run rather than degrading silently. |
| V | Agent-friendly analytics surface | **Load-bearing.** This whole feature is the consumer that Principle V was written to protect. | The agent enforces V by allowlist (FR-009), by encoding the count rule in prompts and tests (FR-012 / SC-008), and by detecting `master_fact` presence (FR-011). The agent does *not* request schema additions or naming changes; new analytics surface is the ETL's responsibility under a separate spec. |
| VI | Two components, one contract | **Load-bearing.** This is the spec that operationalizes "one contract". | Strict directory split (`agent/`); separate `pyproject.toml`; separate `Dockerfile`; separate `docker-compose.yml`; statically-enforced no-cross-imports test; DuckDB mounted read-only as the only data path between the components; no shared utilities introduced in V1 (any future shared package is a separate decision). |

**Plan gate verdict**: PASS — no Complexity Tracking entries.
The two clarifications resolved at spec time (provider, multi-turn
depth) are scope decisions, not constitution violations. The
Constitution VI/Boundary-artifact constraints are met by
construction (separate top-level dir + read-only DuckDB mount +
no cross-imports). Principle V is satisfied by allowlist +
prompted count rule + golden test.

No constitution amendment required: Constitution v1.1.0 already
defers the agent's framework, model choice, and sandboxing
strategy to "the agent's own initial spec" (Technical Constraints
/ Components & runtime targets) — which is exactly this spec.

## Project Structure

### Documentation (this feature)

```text
specs/004-agent-v1/
├── plan.md              # this file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (entities + Postgres schema)
├── quickstart.md        # Phase 1 output (operator runbook)
├── checklists/
│   └── requirements.md  # spec quality checklist (already passing)
├── contracts/           # Phase 1 output
│   ├── api.md           # FastAPI endpoints (request/response shapes)
│   ├── graph.md         # LangGraph state + node/edge contract
│   ├── tools.md         # tool I/O schemas and node-tool allowlist
│   ├── sql-safety.md    # allowed/forbidden SQL contract
│   ├── code-generation.md  # generated-code shape + RESULT contract
│   └── postgres-schema.md  # agent_* tables (DDL-flavored)
├── spec.md              # already drafted
└── tasks.md             # produced by /speckit-tasks (not yet)
```

### Source Code (repository root)

```text
# Existing — do not touch
etl/                      # spec 001/002/003 component
data/                     # shared with etl; gitignored except fixtures
docs/
specs/
.specify/

# New — produced by this feature
agent/
├── pyproject.toml        # `discogs_agent` package, deps pinned
├── Dockerfile            # python:3.12-slim, runs uvicorn
├── README.md             # operator quickstart (mirrors quickstart.md)
├── .env.example          # OPENAI_API_KEY=, DATABASE_URL=, ...
├── src/
│   └── discogs_agent/
│       ├── __init__.py
│       ├── api.py        # FastAPI app: /query, /threads, /runs, /artifacts, /health
│       ├── cli.py        # optional dev CLI: `python -m discogs_agent.cli query "..."`
│       ├── config.py     # env-driven settings (pydantic-settings)
│       │
│       ├── graph/
│       │   ├── __init__.py
│       │   ├── state.py     # AgentState TypedDict
│       │   ├── builder.py   # StateGraph wiring + compile()
│       │   └── nodes/
│       │       ├── load_schema.py
│       │       ├── router.py
│       │       ├── query_understanding.py
│       │       ├── code_generator.py
│       │       ├── sql_safety_checker.py
│       │       ├── sandbox_executor.py
│       │       ├── chart_validator.py
│       │       └── response_synthesizer.py
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py            # @tool decorator + persistence shim
│       │   ├── dataset_schema_reader.py
│       │   ├── query_classifier.py
│       │   ├── sql_safety_checker.py
│       │   ├── sandbox_executor.py
│       │   ├── chart_validator.py
│       │   ├── cost_logger.py
│       │   └── artifact_store.py
│       │
│       ├── prompts/
│       │   ├── router.md
│       │   ├── query_understanding.md
│       │   ├── code_generator.md
│       │   ├── repair_code.md
│       │   └── response_synthesizer.md
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py          # OpenAI client factory + tier mapping
│       │   ├── stub.py            # deterministic stub for tests
│       │   └── pricing.py         # rate card for cost estimation
│       │
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── db.py              # SQLAlchemy engine / session factory
│       │   ├── models.py          # ORM models (agent_threads, ...)
│       │   ├── repositories.py    # thin DAOs per table
│       │   └── migrations/
│       │       ├── env.py
│       │       └── versions/
│       │           └── 0001_initial.py
│       │
│       ├── sandbox/
│       │   ├── __init__.py
│       │   ├── runner.py          # subprocess boot + capture
│       │   └── restrictions.py    # env strip, rlimits, cwd jail
│       │
│       ├── duckdb_layer/
│       │   ├── __init__.py
│       │   ├── schema.py          # introspect published DuckDB
│       │   └── allowlist.py       # allowed tables/views constant
│       │
│       └── observability/
│           ├── __init__.py
│           ├── logging.py         # structlog setup
│           └── tracing.py         # graph-step span recorder
│
└── tests/
    ├── conftest.py                # seed-duckdb + postgres fixtures
    ├── fixtures/
    │   ├── seed_duckdb.py         # builds tests/fixtures/seed.duckdb
    │   └── seed.duckdb            # tiny DuckDB committed for tests
    ├── unit/
    │   ├── test_dataset_schema_reader.py
    │   ├── test_query_classifier.py
    │   ├── test_sql_safety_checker.py
    │   ├── test_sandbox_executor.py
    │   ├── test_chart_validator.py
    │   ├── test_cost_logger.py
    │   ├── test_artifact_store.py
    │   ├── test_router_node.py
    │   ├── test_query_understanding_node.py
    │   ├── test_code_generator_node.py
    │   ├── test_response_synthesizer_node.py
    │   ├── test_prompts_render.py
    │   ├── test_no_etl_imports.py     # static cross-component check
    │   └── test_count_rule_in_prompt.py
    ├── integration/
    │   ├── test_agent_simple_query.py
    │   ├── test_agent_complex_query.py
    │   ├── test_agent_unsupported_query.py
    │   ├── test_agent_clarification_query.py
    │   ├── test_agent_safety_block.py
    │   ├── test_agent_sandbox_failure.py
    │   ├── test_agent_resume_thread.py
    │   ├── test_duckdb_contract.py
    │   ├── test_master_fact_optional.py
    │   ├── test_persistence_survives_restart.py
    │   └── test_health.py
    ├── graph/
    │   ├── test_path_simple.py
    │   ├── test_path_complex.py
    │   ├── test_path_unsupported.py
    │   ├── test_path_clarification.py
    │   ├── test_path_safety_retry.py
    │   ├── test_path_validation_retry.py
    │   └── test_path_retries_exhausted.py
    └── golden/
        ├── test_golden_releases_by_decade.py
        ├── test_golden_techno_over_time.py
        ├── test_golden_vinyl_vs_cd.py
        ├── test_golden_label_diversity.py
        ├── test_golden_house_outliers.py
        └── test_golden_master_versions.py

# Root of monorepo
docker-compose.yml        # ties agent + postgres; mounts DuckDB ro + artifacts rw
.env.example              # template; .env stays gitignored
.gitignore                # gains: agent/.venv/, agent/dist/, artifacts/, agent/tests/fixtures/seed.duckdb (?)
```

**Structure Decision**: containerized web service with a single
`agent/` top-level directory paralleling the existing `etl/`
component (Constitution VI). Tests partition by stratum
(`unit/`, `integration/`, `graph/`, `golden/`) so the LLM-stub
suites can run cheaply on every change while the
OpenAI-live golden suite stays manual / opt-in. The seed DuckDB
**is** committed (~50–100 KB, deterministically built); the
seed-builder script lives next to it for transparent
reproducibility (the same pattern the ETL uses for its small
fixtures).

> **Note on `docker-compose.yml` location**: it sits at the
> repo root rather than inside `agent/` because it composes
> *both* the agent service *and* a Postgres sibling, and it
> mounts the shared `data/published/duckdb/` directory into
> the agent container. Keeping it at root makes the
> bind-mount paths obvious and matches typical monorepo
> Docker conventions. The root `.env` is what
> `docker-compose.yml` reads.

## Complexity Tracking

> No entries — Constitution Check passed without violations.
> The two clarifications resolved at spec time (provider,
> multi-turn depth) are scope decisions captured in the spec.
> Both load-bearing principles (V and VI) are satisfied by
> construction.
