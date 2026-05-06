# Tasks: Discogs Conversational Analytics Agent — V1

**Input**: Design documents from `/specs/004-agent-v1/`
**Prerequisites**:
- Plan: [plan.md](./plan.md)
- Spec: [spec.md](./spec.md)
- Research: [research.md](./research.md)
- Data model: [data-model.md](./data-model.md)
- Contracts: [contracts/api.md](./contracts/api.md),
  [contracts/graph.md](./contracts/graph.md),
  [contracts/tools.md](./contracts/tools.md),
  [contracts/sql-safety.md](./contracts/sql-safety.md),
  [contracts/code-generation.md](./contracts/code-generation.md),
  [contracts/postgres-schema.md](./contracts/postgres-schema.md)
- Quickstart: [quickstart.md](./quickstart.md)

**Tests**: included — the spec defines test-anchored success
criteria (SC-002 through SC-009) and the plan documents an
explicit unit / graph / integration / golden / docker-smoke
test stratification. Tests are not optional for this feature.

**Components touched**: `agent/` only (Constitution Principle VI).
Zero edits to `etl/`. The published DuckDB at
`data/published/duckdb/discogs.duckdb` is the only contact
surface.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no
  dependencies on incomplete tasks).
- **[Story]**: Which user story this task belongs to (US1, US2,
  US3, US4).
- File paths are absolute relative to the repo root and should
  be created/edited as named.

## Path Conventions

- Agent component: `agent/`
- Source: `agent/src/discogs_agent/`
- Tests: `agent/tests/`
- Compose root: `docker-compose.yml` (repo root); `.env` /
  `.env.example` at repo root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: scaffold the `agent/` top-level component with its
own dependency manifest, tooling, and Docker stack so all
later phases have a place to land code.

- [X] T001 Create the `agent/` directory tree per [plan.md §"Project Structure"](./plan.md): `agent/`, `agent/src/discogs_agent/`, all subpackages (`graph/`, `graph/nodes/`, `tools/`, `prompts/`, `llm/`, `persistence/`, `persistence/migrations/versions/`, `sandbox/`, `duckdb_layer/`, `observability/`), and `agent/tests/` with `unit/`, `integration/`, `graph/`, `golden/`, `fixtures/` subdirs. Add `__init__.py` to every Python subpackage.
- [X] T002 [P] Create `agent/pyproject.toml` declaring the `discogs_agent` package with dependencies pinned per [plan.md "Primary Dependencies"](./plan.md): `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `langgraph`, `langchain-core`, `langchain-openai`, `openai`, `sqlalchemy>=2`, `psycopg[binary]`, `alembic`, `duckdb`, `plotly`, `pandas`, `tiktoken`, `sqlparse`, `structlog`. Test extra: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `testcontainers[postgres]`. Dev extra: `ruff`, `mypy`.
- [X] T003 [P] Create `agent/Dockerfile`: base `python:3.12-slim`, install build deps, `pip install -e '.[test]'`, working dir `/app`, expose 8000, entrypoint runs `alembic upgrade head` then `uvicorn discogs_agent.api:app --host 0.0.0.0 --port 8000`.
- [X] T004 [P] Create `docker-compose.yml` at the repo root with two services: `agent-api` (built from `agent/Dockerfile`, env-file `.env`, mounts `./data/published/duckdb:/app/data/published/duckdb:ro` and `./artifacts:/app/artifacts`, depends_on `postgres`, healthcheck hits `/health`) and `postgres` (image `postgres:16-alpine`, named volume `postgres_data:/var/lib/postgresql/data`, env from `.env`).
- [X] T005 [P] Create `.env.example` at the repo root with all variables from [research.md R-13](./research.md): `OPENAI_API_KEY=`, `ANALYTICS_DUCKDB_PATH=...`, `DATABASE_URL=...`, `ARTIFACTS_DIR=...`, `CHEAP_MODEL=gpt-4o-mini`, `STRONG_MODEL=gpt-4o`, `MAX_RETRIES=2`, `SANDBOX_TIMEOUT_SECONDS=30`, `THREAD_CARRYOVER_TURNS=4`, `THREAD_CARRYOVER_TOKEN_BUDGET=512`, `LLM_BACKEND=openai`, `LOG_LEVEL=INFO`, `AGENT_ADMIN_TOKEN=`. Comment each block.
- [X] T006 [P] Update root `.gitignore` to add: `agent/.venv/`, `agent/dist/`, `agent/build/`, `agent/*.egg-info/`, `artifacts/`. Confirm `.env` is already ignored at root (it is — keep it that way).
- [X] T007 [P] Configure `agent/pyproject.toml` `[tool.ruff]` (line length 100, target py312) and `[tool.mypy]` (`strict = true` over `discogs_agent`, ignore_missing_imports for langgraph/openai if needed), `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, asyncio mode auto).
- [X] T008 Create `agent/README.md` with a 1-page operator quickstart that mirrors [quickstart.md §1–§3](./quickstart.md) — env setup, `docker compose up`, golden query. Link to the spec for the long-form runbook.
- [X] T009 Initialize Alembic in `agent/src/discogs_agent/persistence/`: create `alembic.ini` (database URL read from env), `migrations/env.py` that imports `discogs_agent.persistence.models.Base.metadata`, empty `migrations/versions/` directory.

**Checkpoint**: `agent/` package importable, image builds clean, compose comes up (with empty endpoints), no migrations yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: build everything every user story needs — config,
persistence, the FastAPI shell with a stub `/health`, the LLM
client factories and stubs, the prompt files, the test
infrastructure, and the static cross-component guard.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Configuration & observability

- [X] T010 Implement `agent/src/discogs_agent/config.py` with `pydantic_settings.BaseSettings` subclass `AgentSettings` exposing every variable from [research.md R-13](./research.md). Add `validate_runtime()` that fails fast if `LLM_BACKEND="openai"` and `OPENAI_API_KEY` is empty, or if `ANALYTICS_DUCKDB_PATH` doesn't exist. Module-level `settings = AgentSettings()`.
- [X] T011 [P] Implement `agent/src/discogs_agent/observability/logging.py` configuring `structlog` to emit JSON; route stdlib logging through it. Expose `get_logger(name)` factory.
- [X] T012 [P] Implement `agent/src/discogs_agent/observability/tracing.py` with the `node_context` ContextVar (used by the tool shim to attribute calls to a node) and helper to record `start_time`/`end_time` for graph steps.

### Persistence layer

- [X] T013 Implement `agent/src/discogs_agent/persistence/models.py` with all six SQLAlchemy 2.x ORM models (`Thread`, `Run`, `ToolCall`, `ModelUsage`, `Artifact`, `Error`) per [contracts/postgres-schema.md §2](./contracts/postgres-schema.md). Use `PG_UUID`/`JSONB`/`TIMESTAMP(timezone=True)` types but make them swappable for SQLite (`String(36)`/`JSON`/`TIMESTAMP`) via a single conditional at the engine boundary (R-07). All check constraints + indexes from §1 included.
- [X] T014 Implement `agent/src/discogs_agent/persistence/db.py`: `engine_factory(url)`, `session_factory(engine)`, FastAPI dependency `get_session`. Detect driver from URL and apply the SQLite-vs-Postgres type adaptation from T013.
- [X] T015 Implement `agent/src/discogs_agent/persistence/repositories.py` with thin DAOs per table — `ThreadRepo`, `RunRepo`, `ToolCallRepo`, `ModelUsageRepo`, `ArtifactRepo`, `ErrorRepo` — each with `create()`, `get(id)`, `list_by_*()` methods needed by the API.
- [X] T016 Write the initial Alembic migration at `agent/src/discogs_agent/persistence/migrations/versions/0001_initial.py` creating all six tables with their indexes and check constraints (DDL from [contracts/postgres-schema.md §1](./contracts/postgres-schema.md)).

### DuckDB layer

- [X] T017 [P] Implement `agent/src/discogs_agent/duckdb_layer/allowlist.py` exporting the constant `ALLOWED_TABLES = ("release_fact", "release_unique_view", "release_artist_bridge", "release_label_bridge", "master_fact")` and a helper `is_allowed(table_name) -> bool`.
- [X] T018 [P] Implement `agent/src/discogs_agent/duckdb_layer/schema.py`: `read_schema_context(duckdb_path) -> SchemaContext` — opens `read_only=True`, lists tables/views via `information_schema.tables`, filters to allowlist, lists columns per table, returns the `SchemaContext` TypedDict per [data-model.md §2.2](./data-model.md). Records non-allowlisted tables as warnings.

### LLM client + stubs + prompts + pricing

- [X] T019 [P] Implement `agent/src/discogs_agent/llm/client.py`: `get_chat_client(model_name) -> BaseChatModel` factory wrapping `langchain_openai.ChatOpenAI`. Reads `OPENAI_API_KEY` from settings.
- [X] T020 [P] Implement `agent/src/discogs_agent/llm/stub.py`: `StubChatModel` that returns deterministic responses keyed by node name + a stable hash of the prompt's user-query field. Activated when `settings.LLM_BACKEND == "stub"`. Records token counts (synthetic but realistic shape).
- [X] T021 [P] Implement `agent/src/discogs_agent/llm/pricing.py`: rate card constant `OPENAI_RATES_2026_04 = {"gpt-4o-mini": (0.15e-6, 0.60e-6), "gpt-4o": (2.50e-6, 10.00e-6), ...}` (input rate, output rate per token); `estimate_cost(model_name, prompt_tokens, completion_tokens) -> Optional[Decimal]` returning `None` for unknown models.
- [X] T022 [P] Author prompt templates as plain markdown with `str.format` placeholders: `agent/src/discogs_agent/prompts/router.md`, `query_understanding.md`, `code_generator.md`, `repair_code.md`, `response_synthesizer.md`. The `code_generator.md` MUST contain the `release_fact` count rule paragraph verbatim per [contracts/code-generation.md §4](./contracts/code-generation.md).

### Graph state & tool base

- [X] T023 Implement `agent/src/discogs_agent/graph/state.py` defining the `AgentState` TypedDict per [data-model.md §2.1](./data-model.md). Pure structure, no behavior.
- [X] T024 Implement `agent/src/discogs_agent/tools/base.py`: the `@traced_tool` decorator that wraps a Pydantic-input/Pydantic-output callable, records `latency_ms`, catches and reclassifies exceptions, redacts known secret keys (`api_key`, `OPENAI_API_KEY`, `DATABASE_URL`) from `input_json`, and persists an `agent_tool_calls` row via `ToolCallRepo`. `node_name` comes from the `node_context` ContextVar (T012).

### FastAPI app shell + stub /health

- [X] T025 Implement `agent/src/discogs_agent/api.py`: a minimal FastAPI `app` with `/health` returning a hardcoded `{"status": "ok"}` (real check lands in US2). Wire startup to call `settings.validate_runtime()` (which fails fast if mis-configured) and `read_schema_context(...)` (which caches the SchemaContext). Wire shutdown if needed for SQLAlchemy disposal.

### Test infrastructure

- [X] T026 Implement `agent/tests/conftest.py`: fixtures for `db_engine` (SQLite `:memory:` by default; Postgres via testcontainers when `AGENT_USE_POSTGRES=1`; auto-skip if Docker unreachable), `db_session`, `seed_duckdb_path` (resolves the committed seed), `llm_stub` (sets `settings.LLM_BACKEND = "stub"`).
- [X] T027 [P] Implement `agent/tests/fixtures/seed_duckdb.py`: a script (idempotent) that builds `agent/tests/fixtures/seed.duckdb` and `seed_no_master.duckdb` with the rows listed in [research.md R-12](./research.md) — ~30 rows in `release_fact` across 4 styles and 3 decades, `release_unique_view` as a real DuckDB view, `release_artist_bridge` (~10 rows), `release_label_bridge` (~10 rows), `master_fact` (~5 rows in the `seed.duckdb` variant; absent in `seed_no_master.duckdb`).
- [X] T028 Run T027 to materialize `agent/tests/fixtures/seed.duckdb` and `agent/tests/fixtures/seed_no_master.duckdb`. Commit both binaries to git.
- [X] T029 [P] Write `agent/tests/unit/test_no_etl_imports.py`: walks every `.py` under `agent/src/discogs_agent/` with `ast`, asserts no `import discogs_etl` or `from discogs_etl ...`. **This test enforces FR-033 and Constitution VI; it MUST pass even before any nodes are implemented.**
- [X] T030 [P] Write `agent/tests/unit/test_seed_duckdb_round_trip.py`: regenerate `seed.duckdb` via T027's script in a temp dir, diff structurally vs the committed binary (table list + row count per table — not byte-equal since DuckDB internals change). Asserts the seed is reproducible from source.

**Checkpoint**: package imports clean, `mypy --strict` passes, `pytest agent/tests/unit/test_no_etl_imports.py agent/tests/unit/test_seed_duckdb_round_trip.py` passes, `docker compose up` brings up both services, `/health` returns `{"status": "ok"}` (stub).

---

## Phase 3: User Story 1 - Ask an analytical question and get an answer with a chart (Priority: P1) 🎯 MVP

**Goal**: end-to-end conversational analytics — user submits a
natural-language question via `POST /query`, agent classifies
+ generates Python+SQL + executes in sandbox + validates chart,
returns response with chart artifact. Includes the four
controlled-failure paths (unsupported, clarification-needed,
safety-exhausted, validation-exhausted) and the
`master_fact`-optional handling.

**Independent Test**: with the foundational stack up and the
seed DuckDB fixture, `POST /query` with the "Show Techno
releases over time" message returns a chart artifact whose
content rendered in a browser is the expected line chart;
`POST /query` with "What is the average price of Techno
releases?" returns `status="failed_unsupported"` with no
opaque crash.

### Tools (US1 substrate)

- [X] T031 [P] [US1] Implement `tools/dataset_schema_reader.py` with the `dataset_schema_reader` tool — Pydantic `SchemaReaderInput` / `SchemaReaderOutput` per [contracts/tools.md §2.1](./contracts/tools.md), wraps `duckdb_layer.schema.read_schema_context`, decorated with `@traced_tool`.
- [X] T032 [P] [US1] Implement `tools/query_classifier.py` with the `query_classifier` tool — accepts `user_query` + `schema_context`, calls the cheap-tier LLM with the `router.md` prompt, parses JSON output to `ClassifierOutput`, decorated with `@traced_tool`.
- [X] T033 [P] [US1] Implement `tools/sql_safety_checker.py` per [contracts/sql-safety.md](./contracts/sql-safety.md): pre-pass DDL/DML token scan via `sqlparse`, AST extraction (`SqlExtractor` from §3.1, including the `read_only=True` structural assertion), DuckDB EXPLAIN with the in-memory schema-stub setup. Returns `SafetyOutput`.
- [X] T034 [P] [US1] Implement `sandbox/restrictions.py`: `preexec_fn` builder applying `RLIMIT_CPU`/`RLIMIT_NOFILE`/`RLIMIT_NPROC`/`RLIMIT_FSIZE` per [contracts/code-generation.md §3.1](./contracts/code-generation.md), and `clean_env(artifact_dir)` returning the minimal env allowlist.
- [X] T035 [P] [US1] Implement `sandbox/wrapper.py`: the small Python harness invoked by the subprocess that `runpy.run_path`s the user-generated code and prints the `RESULT` (or exception) between `__AGENT_RESULT_BEGIN__` / `__AGENT_RESULT_END__` markers as JSON.
- [X] T036 [US1] Implement `sandbox/runner.py`: `run_in_sandbox(generated_code, thread_id, run_id, timeout_seconds) -> SandboxOutput` — writes `generated_code` to a temp file inside the per-run artifact dir, spawns `python -I -B -S` via `subprocess.Popen` with the preexec/env from T034, waits with timeout, parses the markers, populates `SandboxOutput`. Depends on T034 + T035.
- [X] T037 [P] [US1] Implement `tools/sandbox_executor.py` with the `sandbox_executor` tool — wraps `sandbox.runner.run_in_sandbox` with `@traced_tool`.
- [X] T038 [P] [US1] Implement `tools/chart_validator.py` with the `chart_validator` tool — applies the validation checklist from [contracts/graph.md §2.7](./contracts/graph.md), returns `ValidatorOutput`.
- [X] T039 [P] [US1] Implement `tools/cost_logger.py` with the `cost_logger` tool — calls `llm.pricing.estimate_cost`, persists to `agent_model_usage`, returns the new `usage_id`.
- [X] T040 [P] [US1] Implement `tools/artifact_store.py` with the `artifact_store` tool — asserts path is inside `ARTIFACTS_DIR/{thread_id}/{run_id}/`, persists to `agent_artifacts`, returns `artifact_id` + `/artifacts/{id}` URL.

### Tool unit tests (US1 substrate)

- [X] T041 [P] [US1] `tests/unit/test_dataset_schema_reader.py`: opens the seed DuckDB, asserts the four core tables present, `has_master_fact=True` for `seed.duckdb`, `False` for `seed_no_master.duckdb`, no `stg_*`/`clean_*` leak through.
- [X] T042 [P] [US1] `tests/unit/test_query_classifier.py`: with the LLM stub, asserts known queries route to the expected complexity bucket; asserts `complexity=unsupported` ⇒ `selected_model is None`.
- [X] T043 [P] [US1] `tests/unit/test_sql_safety_checker.py`: covers all rows in [contracts/sql-safety.md §6](./contracts/sql-safety.md) — `test_safety_blocks_drop`, `test_safety_blocks_insert`, `test_safety_blocks_read_parquet`, `test_safety_blocks_stg_table`, `test_safety_blocks_clean_table`, `test_safety_blocks_format_summary`, `test_safety_requires_read_only`, `test_safety_passes_techno_query`, `test_safety_passes_label_diversity_query`, `test_safety_blocks_master_fact_when_absent`, `test_safety_explain_plan_recorded`, `test_safety_blocks_url_literal`.
- [X] T044 [P] [US1] `tests/unit/test_sandbox_executor.py`: covers `test_sandbox_clean_success`, `test_sandbox_timeout`, `test_sandbox_no_pkg_install` (no `pip` on PATH), `test_sandbox_no_secret_leak` (`OPENAI_API_KEY`/`DATABASE_URL`/`AWS_*` absent in subprocess `os.environ`), `test_sandbox_runs_seed_query` (uses `seed.duckdb`, hand-written valid script, asserts chart appears + `RESULT` shape).
- [X] T045 [P] [US1] `tests/unit/test_chart_validator.py`: each item in [contracts/graph.md §2.7](./contracts/graph.md) validation checklist gets a true / false case (file missing, wrong extension, `RESULT` missing, `row_count` mismatch, etc.).
- [X] T046 [P] [US1] `tests/unit/test_cost_logger.py`: known model name → real cost; unknown → `None` + warning logged; row written to `agent_model_usage`.
- [X] T047 [P] [US1] `tests/unit/test_artifact_store.py`: path-inside-artifact-dir guard rejects paths outside; `.html` extension required for `plotly_html`; row written to `agent_artifacts`.
- [X] T048 [P] [US1] `tests/unit/test_count_rule_in_prompt.py`: reads `prompts/code_generator.md`, asserts the count-rule paragraph is present verbatim (per [contracts/code-generation.md §4](./contracts/code-generation.md)).
- [X] T049 [P] [US1] `tests/unit/test_node_tool_allowlist.py`: imports the allowlist mapping from T024 / `tools/base.py` and asserts it matches [contracts/tools.md §3](./contracts/tools.md) verbatim — every node lists exactly the allowed tools.

### Graph nodes

- [X] T050 [P] [US1] Implement `graph/nodes/load_schema.py` per [contracts/graph.md §2.1](./contracts/graph.md): caches the `SchemaContext` in module state on first call, returns from cache thereafter; populates `state.schema_context`.
- [X] T051 [P] [US1] Implement `graph/nodes/router.py` per [contracts/graph.md §2.2](./contracts/graph.md): calls `query_classifier`; populates `state.route` with `{complexity, selected_model, rationale}`. Maps `simple → CHEAP_MODEL`, `complex → STRONG_MODEL`, others → `None`.
- [X] T052 [P] [US1] Implement `graph/nodes/query_understanding.py` per [contracts/graph.md §2.3](./contracts/graph.md): builds the analytical plan via the strong-or-cheap LLM (per `state.route.selected_model`), populates `state.query_plan`. Carry-over preamble injection deferred to US4 — for US1 leave a TODO that resolves in T100.
- [X] T053 [P] [US1] Implement `graph/nodes/code_generator.py` per [contracts/graph.md §2.4](./contracts/graph.md): selects `code_generator.md` on first entry, `repair_code.md` on retry; calls the LLM at the chosen tier; populates `state.generated_code`; increments `state.retry_count`.
- [X] T054 [P] [US1] Implement `graph/nodes/sql_safety_checker.py` per [contracts/graph.md §2.5](./contracts/graph.md): wraps the `sql_safety_checker` tool; populates `state.generated_sql` (extracted) + `state.safety_result`.
- [X] T055 [P] [US1] Implement `graph/nodes/sandbox_executor.py` per [contracts/graph.md §2.6](./contracts/graph.md): wraps the `sandbox_executor` + `artifact_store` tools; populates `state.execution_result`, `state.artifact_paths`, `state.dataframe_preview`.
- [X] T056 [P] [US1] Implement `graph/nodes/chart_validator.py` per [contracts/graph.md §2.7](./contracts/graph.md): wraps the `chart_validator` tool; populates `state.validation_result` including the `should_retry` flag.
- [X] T057 [P] [US1] Implement `graph/nodes/response_synthesizer.py` per [contracts/graph.md §2.8](./contracts/graph.md): branches by `state.route.complexity` + safety/validation result per the §2.8 branch table; calls the cheap-tier LLM with `response_synthesizer.md`; populates `state.final_response`. Prompt must forbid raw tracebacks (FR-024).

### Graph builder + persistence shim

- [X] T058 [US1] Implement `graph/builder.py`: assembles a `StateGraph[AgentState]` wiring the eight nodes per [contracts/graph.md §1](./contracts/graph.md) topology. Conditional edges for `router_edge`, `safety_edge`, `validation_edge` per §2. `compile()` returns a runnable. Depends on T050–T057.
- [X] T059 [US1] Implement the persistence shim in `graph/builder.py` (or a sibling `graph/shim.py`) per [contracts/graph.md §3](./contracts/graph.md): after each node returns, diff `state.tool_calls` / `state.model_usage` / `state.errors` against the prior length and persist the deltas via the repos. Update non-terminal `agent_runs` fields (complexity, selected_model, generated_sql, metadata.retry_count) as they become known.

### POST /query endpoint + artifact serving

- [X] T060 [US1] Implement Pydantic request/response DTOs in `api.py` (or a sibling `api_dtos.py`) for `POST /query` per [contracts/api.md §1](./contracts/api.md): `QueryRequest`, `QueryResponse`, `ErrorEnvelope`. Status codes per the §1 error table.
- [X] T061 [US1] Implement `POST /query` in `api.py`: creates the `agent_threads` row (or 404 on unknown thread_id), creates the `agent_runs` row in `running` status, builds the initial `AgentState`, invokes `graph.builder.compile().invoke(state)`, projects the final state to the response DTO, updates `agent_runs` to its terminal status. On any uncaught exception, records `agent_errors` row with `error_type=unexpected` and returns `500 internal_error` (no traceback in body — FR-024).
- [X] T062 [P] [US1] Implement `GET /artifacts/{artifact_id}` in `api.py` per [contracts/api.md §4](./contracts/api.md): looks up `path` from `agent_artifacts`, normalizes, asserts inside `ARTIFACTS_DIR`, returns `FileResponse(media_type="text/html")`. 404 on miss or path-traversal.

### Graph path tests

- [X] T063 [P] [US1] `tests/graph/test_path_simple.py`: stub LLM routes a query as `simple` with a valid SQL response that passes safety, sandbox produces a valid chart; assert run ends in `succeeded`, `retry_count=0`, all 7 tools invoked at least once.
- [X] T064 [P] [US1] `tests/graph/test_path_complex.py`: as above but for `complex` (strong-tier model).
- [X] T065 [P] [US1] `tests/graph/test_path_unsupported.py`: stub LLM returns `unsupported`; assert no codegen, no sandbox call, status `failed_unsupported`.
- [X] T066 [P] [US1] `tests/graph/test_path_clarification.py`: stub LLM returns `clarification_needed`; assert no codegen, no sandbox call, status `failed_clarification_needed`.
- [X] T067 [P] [US1] `tests/graph/test_path_safety_retry.py`: stub LLM emits a forbidden table on the 1st code-gen call, a clean SQL on the 2nd; assert run ends `succeeded` with `retry_count=1`.
- [X] T068 [P] [US1] `tests/graph/test_path_validation_retry.py`: stub LLM emits valid SQL but the 1st generated code fails validation (e.g., `RESULT` missing), 2nd succeeds; assert run ends `succeeded` with `retry_count=1`.
- [X] T069 [P] [US1] `tests/graph/test_path_retries_exhausted.py`: stub LLM emits forbidden SQL on every attempt; assert run ends `failed_safety` after `MAX_RETRIES` exhausted; final response contains no traceback.

### US1 integration tests

- [X] T070 [P] [US1] `tests/integration/test_agent_simple_query.py`: spins up a SQLite-backed test app + seed DuckDB; `POST /query` with the "Show Techno releases over time" question (using the LLM stub); asserts response contains chart_artifact url, sql containing `COUNT(DISTINCT release_id)` or `release_unique_view`, status `succeeded`. Verifies SC-008 anchor.
- [X] T071 [P] [US1] `tests/integration/test_agent_complex_query.py`: as above but for the label-diversity question.
- [X] T072 [P] [US1] `tests/integration/test_agent_unsupported_query.py`: posts "What is the average price of Techno releases?"; asserts `status=failed_unsupported`, no `sql` returned, no chart, response explains missing field.
- [X] T073 [P] [US1] `tests/integration/test_agent_clarification_query.py`: posts "Show me the best labels"; asserts `status=failed_clarification_needed`, response asks for a metric.
- [X] T074 [P] [US1] `tests/integration/test_agent_safety_block.py`: stub forces the generator to emit a forbidden table on every retry; asserts `status=failed_safety`, response is controlled (no traceback), no DuckDB write occurred (file SHA-256 unchanged before/after — partial SC-007).
- [X] T075 [P] [US1] `tests/integration/test_agent_sandbox_failure.py`: stub forces the generator to emit code that raises at runtime on every retry; asserts `status=failed_validation`, no traceback in response body.
- [X] T076 [P] [US1] `tests/integration/test_master_fact_optional.py`: uses `seed_no_master.duckdb`; asks "Which works have the most versions?"; asserts router classifies as `unsupported` and the response names master_fact-style data as missing for this snapshot. Also asks "Show Techno releases over time" against the same snapshot and asserts it succeeds normally (FR-011).
- [X] T077 [US1] `tests/integration/test_duckdb_contract.py`: smoke-checks that the agent never opens DuckDB write-mode by computing SHA-256 of `seed.duckdb` before and after running the full integration suite (or a documented batch of queries). Asserts byte-equality (SC-007).

**Checkpoint**: US1 fully functional. All seven acceptance scenarios from [spec.md US1](./spec.md) demonstrable. The Constitution VI guarantee (no DuckDB mutation, no ETL imports) is verified by tests. MVP shippable.

---

## Phase 4: User Story 2 - Run the whole agent stack locally with Docker Compose (Priority: P2)

**Goal**: realistic `/health` that distinguishes DuckDB and
Postgres reachability; Compose stack durable across restarts;
gated docker smoke test; honest failure reporting when
dependencies are absent.

**Independent Test**: from a clean checkout with `.env`
configured and a published DuckDB in place, `docker compose up`
brings up both services; `/health` returns `status: ok` with
both checks green; the golden query succeeds; `down` + `up`
preserves prior runs (Postgres volume durable).

### /health real implementation

- [X] T078 [US2] Implement the real `/health` in `api.py` per [contracts/api.md §5](./contracts/api.md) and [research.md R-10](./research.md): runs the DuckDB check (file exists, opens read-only, four core tables present, `has_master_fact` reported), runs the Postgres check (`SELECT 1` with a 1-second timeout), aggregates; returns `200` when ok else `503`. Reports `version` from a baked-in build arg or "dev" when absent. Replaces the T025 stub.
- [X] T079 [P] [US2] `tests/unit/test_health.py`: covers DuckDB-missing, DuckDB-missing-tables, DuckDB-without-master_fact (still ok), Postgres-down, both-down, and both-up cases. Uses tmp paths and a SQLite engine wrapped to fake the `SELECT 1` failure modes.
- [X] T080 [US2] `tests/integration/test_health.py`: against the seed DuckDB and a real (testcontainers) Postgres, hit `/health` and assert `status: ok`, `duckdb.has_master_fact: true`, `postgres.ok: true`, version field present.

### Compose finalization + persistence durability

- [X] T081 [US2] Verify and (if needed) tighten `docker-compose.yml` per [quickstart.md §2](./quickstart.md): `agent-api` healthcheck hits `/health` every 10 s with a 30-second start period; `postgres` healthcheck via `pg_isready`; `agent-api.depends_on.postgres.condition: service_healthy`; named `postgres_data` volume; bind mount for `./data/published/duckdb` `:ro` and `./artifacts` `:rw`; `restart: unless-stopped`. (Plus: `AGENT_VERSION` build arg → `Dockerfile` ENV so `/health.version` reports the SHA when set.)
- [X] T082 [US2] `tests/integration/test_persistence_survives_restart.py`: with the integration stack up, create a thread + run via the API, dispose the SQLAlchemy engine, recreate it (simulating a process restart against the same DB), GET the run by id and assert it returns the same row. Validates SC-009 at the persistence-layer level.
- [X] T083 [US2] Author `agent/tests/integration/test_docker_smoke.py` (gated on `AGENT_DOCKER_SMOKE=1`): `subprocess.run(["docker", "compose", "up", "-d", "--build"])`, polls `/health` until ok, posts the golden simple query, asserts a chart artifact lands on disk under `./artifacts/`, confirms a row in `agent_runs`. `compose down` in teardown. Runs no LLM-stub override — uses real OpenAI if a key is provided, else the test skips.
- [X] T084 [US2] Update `agent/README.md` with the operator runbook diff: bring-up, health polling, golden query, restart-durability check, tear-down — mirrors [quickstart.md §2–§7](./quickstart.md). Real command output capture deferred to a manual T083 run.

**Checkpoint**: US2 demonstrable end-to-end. SC-001 (15-min time-to-chart from a clean checkout), SC-009 (persistence survives restart), and the SC-003 health-failure path all reachable.

---

## Phase 5: User Story 3 - Inspect what happened on any prior run (Priority: P2)

**Goal**: full trace transparency via `/threads/{id}` and
`/runs/{id}`; admin-mode (gated by header + env) reveals
generated code and tracebacks; everything else is inspectable
to non-admin clients without secret leaks.

**Independent Test**: submit any query (success or controlled
failure), capture `run_id`, GET `/runs/{run_id}` and observe
the route, generated SQL, all tool calls, model-usage entries,
and the artifact reference. Without admin header, generated
code is `null` and `errors[].traceback` is `null`. With admin
header + `AGENT_ADMIN_TOKEN` matched, those are populated.

### Admin auth + DTOs

- [X] T085 [P] [US3] Implement `agent/src/discogs_agent/api_admin.py` (or merge into `api.py`): a FastAPI dependency `is_admin(request)` that returns `True` only when `settings.AGENT_ADMIN_TOKEN` is non-empty AND the request carries `X-Agent-Admin: <token>` matching it. Default deny.
- [X] T086 [P] [US3] Implement Pydantic response DTOs for `GET /threads/{id}` and `GET /runs/{id}` per [contracts/api.md §2 / §3](./contracts/api.md), with optional `generated_code` and `errors[].traceback` fields populated only by the admin-aware serializer.

### Endpoints

- [X] T087 [US3] Implement `GET /runs/{run_id}` in `api.py`: joins `agent_runs` + `agent_tool_calls` + `agent_model_usage` + `agent_errors` + `agent_artifacts`; serializes per the DTO; includes `generated_code` and tracebacks only when `is_admin` is `True`. 404 on miss.
- [X] T088 [US3] Implement `GET /threads/{thread_id}` in `api.py`: returns thread metadata + paginated runs (`limit`, `offset` query params) per [contracts/api.md §2](./contracts/api.md). Each run's `primary_artifact` is the earliest `agent_artifact` for that run (single LATERAL or per-run subquery).

### US3 integration tests

- [X] T089 [P] [US3] `tests/integration/test_runs_endpoint_default.py`: submit a successful query, GET the run, assert non-admin payload — tool_calls populated, model_usage populated, generated_code is `null`, errors[].traceback is `null` (or absent for safety/validation buckets which already have `null`).
- [X] T090 [P] [US3] `tests/integration/test_runs_endpoint_admin.py`: with `AGENT_ADMIN_TOKEN=test-token` and the matching header, the same endpoint returns generated_code (string) and errors[].traceback for unexpected-bucket errors. Without the header, returns the non-admin shape.
- [X] T091 [P] [US3] `tests/integration/test_runs_endpoint_no_admin_secret.py`: submit a deliberate sandbox failure, GET the run as a non-admin, assert no string in the JSON body matches `Traceback (most recent` or `OPENAI_API_KEY` (literal grep over the serialized body).
- [X] T092 [P] [US3] `tests/integration/test_threads_endpoint.py`: create three runs under one thread, GET the thread, assert `run_count=3` and runs are listed in chronological order with their primary artifact urls populated for the successful ones.
- [X] T093 [P] [US3] `tests/integration/test_threads_endpoint_pagination.py`: create 5 runs, query with `limit=2`, assert exactly 2 returned; query with `offset=2&limit=2`, assert the next 2; `offset=4&limit=2` returns 1.
- [X] T094 [P] [US3] `tests/integration/test_runs_endpoint_404.py`: GET a random UUID, expect 404 with `code=run_not_found`.

**Checkpoint**: US3 demonstrable. Inspection endpoints reveal full trace; admin path is secret-aware; default path leaks nothing. SC-005 verifiable.

---

## Phase 6: User Story 4 - Continue a prior conversation (Priority: P3)

**Goal**: light contextual carry-over — when a `thread_id` is
reused, the prior runs' user-query *text* (only) feeds into
the new run's `query_understanding` prompt, capped by
`THREAD_CARRYOVER_TURNS` and `THREAD_CARRYOVER_TOKEN_BUDGET`.

**Independent Test**: submit two queries against the same
thread; assert (a) both runs are visible under
`/threads/{id}` (already tested in US3); (b) the second
query's persisted `agent_runs.metadata.carryover` contains the
first query's text but no SQL/code; (c) a follow-up phrasing
("now compare that to House") routes correctly when carry-over
is enabled and is misclassified or noisily-routed when
carry-over is disabled — proves the preamble is doing
something.

### Carry-over implementation

- [ ] T095 [US4] Implement `agent/src/discogs_agent/graph/nodes/_carryover.py`: `build_carryover_preamble(prior_runs, token_budget) -> tuple[str | None, int]` per [research.md R-04](./research.md). Reads the last `THREAD_CARRYOVER_TURNS` runs of statuses `succeeded` / `failed_clarification_needed`, formats a "Recent conversation:" preamble, drops trailing turns until total tokens (via `tiktoken`) fit the budget. Returns `(preamble, turn_count)`.
- [ ] T096 [US4] Wire T095 into `graph/nodes/query_understanding.py` (replacing the TODO from T052): fetch prior runs via `RunRepo.fetch_recent_for_thread(thread_id, limit, statuses)` (add this method to `repositories.py` if absent), call `build_carryover_preamble`, populate `state.carryover_preamble` and `state.carryover_turn_count`, inject into the prompt only when non-`None`.
- [ ] T097 [US4] In `POST /query` (T061), after the run finishes, write the carry-over preamble + turn count into `agent_runs.metadata_json.carryover` for traceability (FR-032).

### US4 unit + integration tests

- [ ] T098 [P] [US4] `tests/unit/test_carryover_builder.py`: empty prior_runs → `(None, 0)`; 1 prior turn within budget → preamble contains its user_query, turn_count=1; many prior turns exceeding budget → trimmed from oldest, turn_count reflects what was kept; tiktoken count never exceeds `THREAD_CARRYOVER_TOKEN_BUDGET` for the produced preamble.
- [ ] T099 [P] [US4] `tests/integration/test_agent_resume_thread.py`: submit a Techno query, capture `thread_id`; submit "now compare that to House" with the same `thread_id`; assert (a) the new run's metadata.carryover.turn_count = 1; (b) the carryover.preamble contains the first query's text; (c) the new run succeeds (router successfully classifies the elliptical query because it has the prior context). Without the same `thread_id`, the same elliptical query should be routed as `clarification_needed` (to demonstrate the carry-over is doing meaningful work).
- [ ] T100 [P] [US4] `tests/integration/test_carryover_no_sql_leak.py`: submit a successful Techno query; submit a follow-up; assert the second run's metadata.carryover does NOT contain the first run's `generated_sql` or `generated_code` (only the user_query text). Verifies the "no SQL/code carry-over" boundary.

**Checkpoint**: US4 demonstrable. Multi-turn works for natural follow-ups; the SQL/code-no-leak invariant is enforced by test.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: golden query suite (the headline demo material),
final docs, and the cross-cutting tests that span phases.

### Golden queries (SC-002 / SC-006 / SC-008 anchor)

- [ ] T101 [P] `tests/golden/test_golden_releases_by_decade.py`: stub LLM returns the canonical SQL from [docs/discogs_agent_initial_spec.md §20.1](../../docs/discogs_agent_initial_spec.md); `POST /query` "Show releases by decade"; assert chart artifact, persisted SQL queries `release_unique_view`, `chart_type=bar`.
- [ ] T102 [P] `tests/golden/test_golden_techno_over_time.py`: as above for §20.2; **MUST assert persisted SQL contains `COUNT(DISTINCT release_id)` OR queries `release_unique_view` exclusively**. Anchors SC-008.
- [ ] T103 [P] `tests/golden/test_golden_vinyl_vs_cd.py`: §20.3; asserts SQL uses `has_vinyl`/`has_cd` and `release_unique_view`.
- [ ] T104 [P] `tests/golden/test_golden_label_diversity.py`: §20.4; asserts SQL joins `release_label_bridge` and `release_fact` with `COUNT(DISTINCT)`.
- [ ] T105 [P] `tests/golden/test_golden_house_outliers.py`: §20.5; asserts SQL contains `WITH ... STDDEV_SAMP`.
- [ ] T106 [P] `tests/golden/test_golden_master_versions.py`: §20.6; uses `seed.duckdb` (with master_fact); asserts SQL queries `master_fact` ordered by `release_count`. With `seed_no_master.duckdb`, the same test variant asserts the run ends `failed_unsupported`.

### Distinct-tools assertion (SC-006)

- [ ] T107 `tests/integration/test_distinct_tools_count.py`: runs the simple golden query, queries `agent_tool_calls` for the resulting `run_id`, asserts the COUNT(DISTINCT tool_name) ≥ 5 (7 expected per [contracts/tools.md §5](./contracts/tools.md)).

### Cross-cutting cleanup

- [ ] T108 [P] Run `ruff check agent/` and fix any lint issues. Run `ruff format agent/`.
- [ ] T109 [P] Run `mypy --strict agent/src/discogs_agent` and fix any type errors. Add `# type: ignore[<rule>]` only where third-party stubs are missing (langgraph or langchain-openai may need this) — never in our own code.
- [ ] T110 Run the full test suite: `pytest agent/tests/`. Confirm 100% pass, including all golden tests. Capture coverage with `pytest --cov=discogs_agent --cov-report=term`. Document achieved coverage in `agent/README.md`.
- [ ] T111 Walk [quickstart.md](./quickstart.md) §1 through §10 manually against a fresh checkout (or a `git stash`-ed working tree) with the seed DuckDB symlinked into `data/published/duckdb/discogs.duckdb`. Capture timing for SC-001 (15-min target). Document any deviations in `agent/README.md`.
- [ ] T112 Optional but recommended: export the compiled LangGraph as a Mermaid diagram via `graph.builder.get_graph().draw_mermaid()`, save to `agent/docs/graph.mmd`. Reference it from `agent/README.md`.

**Checkpoint**: V1 ready to demo. SC-001 through SC-010 all verifiable. The branch is mergeable.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Phase 1 — BLOCKS all user stories.
- **US1 (Phase 3)**: depends on Phase 2.
- **US2 (Phase 4)**: depends on Phase 2 + parts of US1 (specifically T061 `POST /query` and T078's predecessor T025 `/health` stub). The US2 docker-smoke test (T083) depends on US1 substantially.
- **US3 (Phase 5)**: depends on Phase 2 + US1 (the inspection endpoints query data populated by US1's runs).
- **US4 (Phase 6)**: depends on US1 (carry-over wires into `query_understanding` from T052 and into `POST /query` from T061).
- **Polish (Phase 7)**: depends on US1+US2+US3+US4 for coverage; the golden suite depends on US1; the distinct-tools count test depends on US1.

### User-story ordering for incremental delivery

```text
Phase 1 + Phase 2  →  Phase 3 (US1, MVP)  →  STOP & DEMO (a)
                  →  Phase 4 (US2)        →  STOP & DEMO (b)
                  →  Phase 5 (US3)        →  STOP & DEMO (c)
                  →  Phase 6 (US4)        →  STOP & DEMO (d)
                  →  Phase 7 (Polish)     →  ship
```

Demos:
- (a): "I can ask the agent a question and get a chart" (the headline).
- (b): "I can run the whole stack locally with one command" (the operator story).
- (c): "I can audit any past run" (the trace story).
- (d): "I can have a multi-turn conversation" (the conversational story).

### Within Each User Story

- Tools & substrate before nodes that use them.
- Nodes before the graph builder.
- Graph builder + persistence shim before the API endpoints.
- Endpoints before the integration tests that exercise them.

### Parallel opportunities

- All of Phase 1 except T001 / T009 can run in parallel ([P] tags T002–T007).
- In Phase 2: T011, T012, T017, T018, T019, T020, T021, T022, T029, T030 can all run in parallel within their respective slots.
- In Phase 3: every tool implementation T031–T040 is parallelizable; every tool unit test T041–T049 is parallelizable; every node implementation T050–T057 is parallelizable; every graph-path test T063–T069 is parallelizable; every US1 integration test T070–T076 is parallelizable.
- T058 (graph builder) is the natural fan-in point — it depends on all 8 nodes.
- T061 (POST /query) depends on T058 + T059 + T060.
- T077 (DuckDB byte-equality) depends on the rest of the US1 integration tests existing (so they can run as the "documented batch").

### Parallel example: US1 tools batch

```bash
# Once T024 (tools/base.py) lands, all seven tools can be implemented in parallel:
T031 tools/dataset_schema_reader.py
T032 tools/query_classifier.py
T033 tools/sql_safety_checker.py
T034 sandbox/restrictions.py     # T036 depends on this
T035 sandbox/wrapper.py          # T036 depends on this
T037 tools/sandbox_executor.py   # depends on T036
T038 tools/chart_validator.py
T039 tools/cost_logger.py
T040 tools/artifact_store.py
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 → Phase 2 → Phase 3.
2. After T077: `pytest agent/tests/`, demo the seven US1 acceptance scenarios manually via `curl`/the CLI, capture screenshots of charts.
3. **STOP and VALIDATE**: this is already a viable shippable MVP. The headline demo (US1 acceptance scenarios 1, 2, 3, 4) works end-to-end.

### Incremental Delivery

1. MVP from above.
2. Add US2 (Phase 4) → demo `docker compose up` + restart durability.
3. Add US3 (Phase 5) → demo `/runs/{id}` and admin mode.
4. Add US4 (Phase 6) → demo "now compare that to House".
5. Add Polish (Phase 7) → ship.

Each "Add X" is a single squash-mergeable PR scoped to its phase.

### Parallel Team Strategy (if applicable)

This V1 is intentionally one-developer-sized, but if multiple
developers were available:

1. Devs share Phase 1 + Phase 2.
2. Once Phase 2 is done:
   - Dev A: Phase 3 (the meat).
   - Dev B: starts on Phase 4 (Compose hardening + health) — only the docker-smoke test (T083) blocks on US1.
   - Dev C: drafts Phase 5 endpoints against in-memory mock data, then integrates once US1 lands.
3. Phase 6 and Phase 7 land last.

---

## Notes

- `[P]` = different files, no dependencies on incomplete tasks.
- Each user story should be independently completable and
  testable — the integration tests for each story exercise its
  own acceptance scenarios without depending on later stories.
- Commit cadence suggestion: one commit per phase, or one
  commit per group within a large phase (e.g., "tools",
  "tool-tests", "nodes", "graph+API", "graph-tests",
  "integration-tests" within US1).
- The seed DuckDB binaries (T028) are committed to git on
  purpose — they keep unit tests fast and make the agent
  testable without re-running the ETL.
- The committed canonical agent design at
  [`docs/discogs_agent_initial_spec.md`](../../docs/discogs_agent_initial_spec.md)
  remains the single source for prompt content shaping —
  consult it when authoring T022.
- Constitution VI compliance is enforced by T029 (no
  cross-imports) + T077 (no DuckDB mutation). Both are
  load-bearing tests — never skip them.

---

## Total: 112 tasks

| Phase | Count |
|-------|------:|
| Phase 1 — Setup | 9 |
| Phase 2 — Foundational | 21 |
| Phase 3 — US1 (P1, MVP) | 47 |
| Phase 4 — US2 (P2) | 7 |
| Phase 5 — US3 (P2) | 10 |
| Phase 6 — US4 (P3) | 6 |
| Phase 7 — Polish | 12 |

Independent-test criteria:
- **US1**: spec.md acceptance scenarios 1–7, exercised by integration tests T070–T076 (see also T077 for the no-mutation invariant).
- **US2**: `docker compose up` + golden query + restart durability via T080–T084.
- **US3**: `/runs/{id}` and `/threads/{id}` payload shape + admin/non-admin payload diff via T089–T094.
- **US4**: carry-over preamble visible in metadata + elliptical follow-up resolves correctly + no SQL/code leakage via T098–T100.

Suggested MVP scope: **Phase 1 + Phase 2 + Phase 3** (US1 only). All seven acceptance scenarios from US1 run end-to-end and the SC-001/SC-002/SC-003/SC-004/SC-006/SC-007/SC-008/SC-010 anchors are reachable. SC-005, SC-009, and the `/threads`-style inspection are deferred to US2/US3.
