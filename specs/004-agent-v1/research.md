# Research: Discogs Conversational Analytics Agent — V1

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Audience**: implementation-side decisions that the spec
deliberately stayed silent on, recorded here so reviewers can
see the trade-offs before they show up as code.

The spec resolved the two scope-level clarifications (provider =
OpenAI; multi-turn = light contextual carry-over). This
research file resolves the **technical decisions** that the plan
needs to commit to before writing any code: how the LangGraph
runs, how the subprocess gets restricted, how Postgres is
shaped, how the tests stay cheap, and what defaults the
operator sees.

Each entry follows: **Decision → Rationale → Alternatives
considered**.

---

## R-01: LangGraph orchestration model

**Decision**: A single compiled `StateGraph[AgentState]` with
the eight nodes from spec Section 8 wired into one fixed
topology. No LangGraph checkpointer in V1; no subgraphs; no
parallel branches.

**Rationale**:
- The spec mandates a deterministic graph (FR-006). A flat
  `StateGraph` with explicit conditional edges is the most
  literal expression of that.
- Subgraphs would buy nothing — there are no nodes whose
  internals need to be opaque to the rest of the graph. They'd
  just hide the retry edges.
- Parallel branches (e.g., running `sql_safety_checker` and
  `sandbox_executor` in parallel) would invalidate the
  ordering guarantee that no forbidden SQL ever executes
  (FR-013/FR-014).
- LangGraph's `StateGraph.compile()` returns a
  pickleable/runnable object that accepts the initial state
  and yields the final state — a clean API surface for the
  FastAPI endpoint.

**Alternatives considered**:
- *LangGraph PregelEngine with checkpointing*: gives free
  resumption mid-graph but adds a moving piece (the
  checkpointer schema lives alongside ours). Deferred — see
  R-05.
- *Hand-rolled state machine* (no LangGraph): meets FR-006 at
  the cost of failing the academic-deliverable contract
  ("LangGraph orchestration"). Rejected on scope.
- *Free-form ReAct agent*: explicitly ruled out by FR-006 and
  by the canonical doc.

---

## R-02: Subprocess sandbox restrictions

**Decision**: The sandbox is a `subprocess.Popen` of
`python -I -B -S` (isolated mode, no `.pyc`, no site-packages
auto-import customizations) with:

- **Working directory** set to the run's
  `artifacts/{thread_id}/{run_id}/` (the only writable place).
- **Environment** stripped to a minimal allowlist:
  `PATH`, `HOME`, `LANG`, `LC_ALL`, plus
  `ANALYTICS_DUCKDB_PATH` and the run's
  `ARTIFACT_DIR`. **`OPENAI_API_KEY` is removed.** No keys, no
  `DATABASE_URL`, no AWS creds.
- **Resource limits** via `resource.setrlimit` in a
  `preexec_fn`: `RLIMIT_CPU` = `SANDBOX_TIMEOUT_SECONDS + 5`
  (belt-and-braces; the wall-clock timeout is the primary
  guard); `RLIMIT_NOFILE` = 64; `RLIMIT_NPROC` = 32;
  `RLIMIT_FSIZE` = 64 MiB (a Plotly HTML on the seed DuckDB
  is ~5 MiB, so 64 MiB is comfortable).
- **Wall-clock timeout** via `Popen.wait(timeout=...)` →
  `Popen.kill()` → `Popen.wait()` on timeout. Default 30 s.
- **Network**: no dedicated network namespace in V1 (would
  require root or unshare); generated code is **not**
  expected to make network calls (the safety check forbids
  httpfs/S3, and the model is prompted not to). The
  documented residual risk: a cleverly-generated `urllib`
  call could reach the host network. Acceptable for a local
  academic demo; closed by the future containerized
  sandbox-worker.
- **Read-only DuckDB**: passed in via env; the generated
  code's responsibility to call `duckdb.connect(..., read_only=True)`.
  The code-generator prompt requires it and the safety check
  asserts the call shape. As an *additional* belt-and-braces
  layer, the bind-mount itself is `:ro` at the Docker level
  (Section "Storage" in plan.md), so even a broken sandbox
  cannot mutate the canonical published DuckDB file.

**Rationale**:
- Belt-and-braces, not single-point-of-failure: the safety
  check + the read-only mount + the rlimits + the env strip
  each guard a different failure mode.
- `python -I -B -S` keeps the sandboxed interpreter from
  pulling in user-customized startup hooks (e.g., a malicious
  `usercustomize.py`). It's the cheapest hardening that
  exists.
- Documented residual risk on networking is honest and
  matches the canonical doc's V1 trade-off (Section 6.3).
  The future sandbox-worker container is the right place to
  fix it.

**Alternatives considered**:
- *`RestrictedPython` / AST whitelisting*: too brittle for
  Plotly/pandas codebases; the LLM produces idioms that
  RestrictedPython rejects.
- *`nsjail` / `bubblewrap`*: better isolation but require
  privileged Docker, complicating the "single command boots"
  story (US2). Out of scope for V1.
- *`firejail`*: linux-only, conflicts with macOS dev.
- *Direct `exec()` in-process*: zero isolation; ruled out
  immediately.

---

## R-03: SQL extraction and safety enforcement

**Decision**: The safety checker uses a **two-pass** approach:

1. **Static AST extraction** — parse the generated Python with
   `ast` and collect all string literals assigned to a name
   matching `^sql$|.*_sql$|^query$|.*_query$` and all
   string literals passed positionally as the first argument
   to `con.execute(...)` / `duckdb.connect(...).execute(...)`.
   This catches the canonical doc's code shape.
2. **DuckDB EXPLAIN check** — every extracted SQL string is
   re-validated by opening a fresh
   `duckdb.connect(":memory:", read_only=False)` (in the agent
   process, *not* the sandbox), running `EXPLAIN <sql>`, and
   inspecting the logical plan for table references via
   `duckdb`'s `con.sql(...).fetchall()`-style introspection.
   Any reference outside the allowlist fails the check.

The DDL/DML keyword check is done first, on the raw SQL
string, with a tokenizer (not a regex) — `sqlparse` from PyPI
handles comment stripping and statement splitting.

**Rationale**:
- The AST pass catches the **structural** shape we expect
  (the canonical generated-code template) cheaply.
- The DuckDB `EXPLAIN` pass is the **semantic** ground truth:
  it sees through `WITH ... SELECT ... FROM`, CTE aliases,
  view references, and resolves subqueries. A regex-only
  approach can't distinguish between "the SQL contains the
  string `read_csv`" and "the SQL actually calls
  `read_csv()`".
- Running `EXPLAIN` in a separate **in-memory** DuckDB
  connection means the safety check itself never touches the
  published file.

**Alternatives considered**:
- *Regex-only allowlist*: misses CTE-aliased forbidden table
  references; trivially fooled by string concatenation.
  Rejected.
- *Run on the real DuckDB with EXPLAIN ONLY*: actually safe
  (EXPLAIN doesn't execute), but couples the safety-check
  latency to the DuckDB file's size and warms its OS cache
  unnecessarily. Rejected.
- *Defer SQL extraction to runtime instrumentation
  (subclass DuckDBPyConnection)*: punts the failure to inside
  the sandbox, which is exactly the wrong direction (we want
  to reject **before** entering the sandbox). Rejected.

---

## R-04: Thread carry-over implementation

**Decision**: Carry-over is implemented by the
`query_understanding` node only. The node:

1. Reads the last `THREAD_CARRYOVER_TURNS=4` runs of the
   current `thread_id` from `agent_runs` (status =
   "succeeded" or "clarification_needed"), most recent first.
2. Drops any whose `user_query` plus the running token total
   would exceed `THREAD_CARRYOVER_TOKEN_BUDGET=512` tokens
   (cheap `tiktoken` count). The remaining queries are
   formatted into a "Recent conversation" preamble.
3. The preamble is injected into the
   `query_understanding` prompt only. Router stays
   stateless. Code generator stays stateless beyond the
   query plan. (This matches "light" — no SQL/code
   carry-over.)
4. The full preamble, if non-empty, is logged to
   `agent_runs.metadata_json.carryover` for traceability
   (FR-032).

**Rationale**:
- Bounded cost: 4 turns × ~100 tokens/turn = ~400 tokens of
  prompt overhead, capped hard at 512.
- Bounded scope: only `query_understanding` cares; routing
  and code generation are unaffected. Easier to test.
- The 4/512 defaults are documented and configurable. Real
  usage will tell us if 4 is enough; the constant lives in
  one place.

**Alternatives considered**:
- *Full message history into every node*: would blur which
  node's behavior depends on what, hurting trace clarity
  and cost.
- *LangGraph's built-in `add_messages` reducer*: tempting
  but ties our state shape to LangGraph internals more than
  needed; we already persist explicitly to Postgres.
- *Vector-store recall over prior queries*: that's RAG,
  which the spec explicitly excludes (Assumptions: No RAG
  in V1).

---

## R-05: Persistence — own tables, no LangGraph checkpointer

**Decision**: V1 persists state through our own SQLAlchemy
ORM models on top of the six `agent_*` tables (see
`contracts/postgres-schema.md`). LangGraph runs without a
checkpointer (the `MemorySaver` default for the duration of
the request).

**Rationale**:
- The persistence model in spec Section 14 is denormalized
  for human readability and inspection-API friendliness; a
  LangGraph checkpointer would persist the **state struct**
  (a serialized blob keyed by thread/checkpoint), which is
  the wrong shape for `GET /runs/{run_id}` to read from.
- Without a checkpointer, **mid-graph resumption** is not
  possible — but the spec doesn't require it. A run either
  completes in one HTTP request or it fails (and the failure
  is recorded). Resumption across requests at the *thread*
  level is a Postgres lookup, not a checkpoint replay.
- One persistence mechanism is easier to reason about than
  two.

**Alternatives considered**:
- *LangGraph `PostgresSaver` checkpointer + our tables*:
  double-bookkeeping. The checkpointer's `checkpoints` and
  `writes` tables would coexist with ours; reviewers would
  ask "which is authoritative?".
- *Checkpointer instead of our tables*: would force every
  `GET /runs/{run_id}` to deserialize a state blob instead
  of joining tables; bad ergonomics.

---

## R-06: Schema for Postgres tables

**Decision**: Six tables matching spec Section 14 verbatim,
with these concrete shape decisions:

- All `*_id` are `UUID` (Python-side `uuid.uuid4()`),
  primary keys; `thread_id`, `run_id`, `tool_call_id`,
  `usage_id`, `artifact_id`, `error_id`. `BIGSERIAL` was
  considered and rejected — UUIDs are stable across
  database resets and avoid leaking ordinal volume to API
  consumers.
- Foreign keys: `agent_runs.thread_id → agent_threads`;
  `agent_tool_calls.run_id`, `agent_model_usage.run_id`,
  `agent_artifacts.run_id`, `agent_errors.run_id` →
  `agent_runs`. `agent_artifacts.thread_id → agent_threads`
  is denormalized for browse-by-thread efficiency
  (matches the inspection endpoint's query shape).
- `*_json` columns are `JSONB`. Indexed where the inspection
  endpoint needs filters (none in V1 beyond the foreign
  keys + a `created_at` index on `agent_runs`).
- Timestamps are `TIMESTAMPTZ` defaulting to `now()`.
- Status enums: implemented as `VARCHAR` with a
  Python-side `enum.StrEnum` rather than Postgres
  `CREATE TYPE` enums, to keep migrations boring.
- `agent_runs.complexity` ∈
  {`simple`, `complex`, `unsupported`, `clarification_needed`}.
  `agent_runs.status` ∈
  {`succeeded`, `failed_safety`, `failed_validation`,
  `failed_unsupported`, `failed_clarification_needed`,
  `failed_internal`}.

**Rationale**:
- UUIDs + JSONB + StrEnums is the boring choice. Migrations
  stay simple; reviewers familiar with SQLAlchemy 2.x will
  read the models in 60 seconds.
- The status enum at the persistence layer is broader than
  the route enum so that retries-exhausted, sandbox-error,
  and validator-error each have their own bucket — useful
  for the inspection API (FR-025).

**Alternatives considered**:
- *MongoDB / DynamoDB*: would force everyone to learn a
  second data model. The trace structure is naturally
  relational (one thread → many runs → many tool_calls).
- *SQLite instead of Postgres*: meets V1 functionally;
  rejected per spec Assumption ("Persistence store:
  Postgres").

---

## R-07: Test database strategy

**Decision**: Unit and graph-path tests use **SQLite** (via
SQLAlchemy with the same models, JSON instead of JSONB —
SQLAlchemy's `JSON` type abstraction handles this) so they
need no Docker. Integration tests use **Postgres via
testcontainers**, gated by an env var that defaults on but
auto-skips with a clear message if Docker isn't reachable.
The Docker smoke test is fully gated (`AGENT_DOCKER_SMOKE=1`).

**Rationale**:
- Unit tests must run in seconds and on any CI machine —
  SQLite is fine because the schema is type-portable
  (UUID-as-CHAR(36), JSONB-as-JSON, TIMESTAMPTZ-as-TIMESTAMP)
  and nothing in the agent's logic depends on JSONB
  operators or Postgres-specific behavior.
- Integration tests hit the real Postgres because that's
  where real bugs live (transaction semantics, JSONB
  serialization round-trips, migration shape).
- The Docker smoke test is a separate stratum because
  building the agent image is slow.

**Alternatives considered**:
- *Postgres-only*: too slow on every save / every PR.
- *SQLite-only*: misses the JSONB-shape bugs; fails to
  validate the production migration path.

---

## R-08: LLM stubbing for tests

**Decision**: A `discogs_agent.llm.stub` module implements an
in-process replacement for the `langchain-openai` chat client
that:

- Routes by **node name + a stable hash of the prompt's
  user-query field** to pre-canned responses.
- Records every call (model, prompt tokens, completion
  tokens) so `cost_logger` and `agent_model_usage` see
  realistic-shaped traces.
- Is selected via the `LLM_BACKEND` env var:
  `LLM_BACKEND=openai` (default) wires the real client;
  `LLM_BACKEND=stub` wires the stub. Tests set
  `LLM_BACKEND=stub` in `conftest.py`.

**Rationale**:
- Unit tests must be deterministic. The stub gives us
  every routing path and every retry edge without paying
  for or waiting on real LLM calls.
- Same env-var swap pattern as the
  `LLM_PROVIDER`-future work but kept as a single switch
  in V1.

**Alternatives considered**:
- *VCR-style HTTP recordings*: brittle to model-name
  changes; couples test fixtures to a specific provider's
  wire format.
- *Live OpenAI calls in unit tests*: cost + flakiness +
  CI complexity. Reserved for the gated golden suite.

---

## R-09: Token counting and cost estimation

**Decision**:

- **Authoritative token counts** come from the OpenAI
  response's `usage` block, written verbatim into
  `agent_model_usage.prompt_tokens` /
  `completion_tokens` / `total_tokens`.
- **Estimated cost** is computed in `llm/pricing.py` from a
  hardcoded rate card (snapshot of OpenAI's published
  per-million-token rates as of the spec date), keyed by
  model name. Unknown model names fall back to estimated
  cost = `NULL` and a warning is logged.
- **No pre-call token estimation** in V1. `tiktoken` is
  available in the env (it's a transitive dep) but unused
  except by the carry-over budget enforcement in R-04.

**Rationale**:
- The spec requires cost estimation (FR-023) but doesn't
  ask for budget enforcement at request time.
- A per-million rate card is honest about its imprecision —
  OpenAI changes rates, so a NULL fallback is preferable
  to silent drift.

**Alternatives considered**:
- *Real-time cost via OpenAI's billing API*: would require
  live API calls every run; over-engineered.
- *Disabling cost field*: violates FR-023.

---

## R-10: Health endpoint definition

**Decision**: `GET /health` returns:

```json
{
  "status": "ok" | "degraded" | "unavailable",
  "checks": {
    "duckdb": {
      "ok": true | false,
      "path": "/app/data/published/duckdb/discogs.duckdb",
      "tables_present": ["release_fact", "release_unique_view", "release_artist_bridge", "release_label_bridge"],
      "has_master_fact": true | false,
      "error": null | "<short message>"
    },
    "postgres": {
      "ok": true | false,
      "error": null | "<short message>"
    }
  },
  "version": "<git sha or 'dev'>",
  "model_provider": "openai"
}
```

- **`ok`** for DuckDB requires: file exists, opens read-only,
  contains all four core tables (`release_fact`,
  `release_unique_view`, `release_artist_bridge`,
  `release_label_bridge`). Missing `master_fact` is **not**
  a failure; it's reported as `has_master_fact = false`.
- **`ok`** for Postgres requires: `SELECT 1` succeeds within
  a 1-second timeout.
- **Aggregate `status`**: `ok` if both checks `ok`;
  `unavailable` if either is not.

**Rationale**:
- Spec FR-030 demands separate signals; spec edge cases
  cover the missing-DuckDB and missing-Postgres failures.
- Reporting `has_master_fact` here lets the operator see at
  a glance whether `master_fact`-dependent queries can be
  asked, without poking at the DuckDB themselves.

**Alternatives considered**:
- *Single boolean `ok`*: too coarse; fails the spec's
  "report separately" requirement.
- *Don't enumerate `tables_present`*: over-cautious — the
  schema reader has already enumerated them at startup, so
  re-reporting them here is free.

---

## R-11: Artifact serving

**Decision**: `GET /artifacts/{artifact_id}` returns the
HTML file via FastAPI's `FileResponse` with
`media_type="text/html"`, after a Postgres lookup that
resolves `artifact_id → path`. The path is normalized and
asserted to be inside `ARTIFACTS_DIR` before opening
(defense-in-depth against path traversal).

**Rationale**:
- A direct file response keeps the chart rendering on the
  client (browser opens the HTML; Plotly inlines its JS).
- Path-traversal check is cheap and load-bearing — without
  it, a corrupted DB row could read arbitrary files.

**Alternatives considered**:
- *Read the HTML and embed it in a JSON envelope*: forces
  the client to do the unwrap; saves nothing.
- *302 redirect to a static-file mount*: would expose the
  whole `artifacts/` tree; bypasses the artifact-id
  lookup that's load-bearing for trace integrity.

---

## R-12: Seed DuckDB fixture

**Decision**: `agent/tests/fixtures/seed.duckdb` is a
~50–100 KB binary committed to git, built by
`agent/tests/fixtures/seed_duckdb.py` from a small in-Python
fixture. The contents:

- `release_fact`: ~30 rows spanning 4 styles (`Techno`,
  `House`, `Vinyl`, `CD`-via-format) and 3 decades.
- `release_unique_view`: a real DuckDB **view** over the
  underlying release rows (so the view-vs-table semantics
  are exercised).
- `release_artist_bridge`: ~10 rows.
- `release_label_bridge`: ~10 rows.
- `master_fact`: present, ~5 rows. (A second fixture,
  `seed_no_master.duckdb`, omits `master_fact` so the
  `master_fact-optional` integration test runs against it.)

The seed-builder script is rerun from CI as a smoke test —
if it diverges from the committed binary, CI fails with a
clear regenerate-and-commit instruction.

**Rationale**:
- Committing the binary keeps unit tests fast (no
  DuckDB-build step on every run).
- The build script is the source of truth for the fixture
  shape — readable in PR review.
- Two variants (`seed.duckdb` and `seed_no_master.duckdb`)
  let us test FR-011 cleanly.

**Alternatives considered**:
- *Build seed at every test run*: ~200 ms cost per session
  is small; rejected only on the grounds that the binary
  is small enough to commit.
- *Use the ETL's release-side fixtures and run a tiny
  ETL*: couples the agent's tests to the ETL's run-time;
  violates the spirit of Constitution VI.

---

## R-13: Configuration & defaults

**Decision**: One `pydantic_settings.BaseSettings`
subclass (`config.AgentSettings`) loaded once at import
time, env-overridable. Defaults:

```python
ANALYTICS_DUCKDB_PATH = "/app/data/published/duckdb/discogs.duckdb"
DATABASE_URL          = "postgresql+psycopg://agent:agent@postgres:5432/agent"
ARTIFACTS_DIR         = "/app/artifacts"
OPENAI_API_KEY        = ""        # required at runtime; empty fails fast
CHEAP_MODEL           = "gpt-4o-mini"
STRONG_MODEL          = "gpt-4o"
MAX_RETRIES           = 2
SANDBOX_TIMEOUT_SECONDS = 30
THREAD_CARRYOVER_TURNS  = 4
THREAD_CARRYOVER_TOKEN_BUDGET = 512
LLM_BACKEND           = "openai"  # "stub" in tests
LOG_LEVEL             = "INFO"
```

`AgentSettings` exposes a `validate_runtime()` method called
from FastAPI's startup hook that fails fast if
`OPENAI_API_KEY` is empty (when `LLM_BACKEND=openai`) or
`ANALYTICS_DUCKDB_PATH` is missing.

**Rationale**:
- One settings class = one place to read in `README.md`.
- Fail-fast on startup is honest — `/health` then never
  has to handle a "no API key" state mid-flight.

**Alternatives considered**:
- *Multiple env-loaded modules*: scatters the source of
  truth; fights the readability story.

---

## Summary of resolved unknowns

| Unknown from plan Technical Context | Resolved in |
|-------------------------------------|-------------|
| Sandbox isolation mechanism | R-02 |
| SQL extraction technique | R-03 |
| Thread carry-over implementation | R-04 |
| LangGraph checkpointer choice | R-05 |
| Postgres schema concretization | R-06 |
| Test database strategy | R-07 |
| LLM stubbing for tests | R-08 |
| Token counting + cost estimation | R-09 |
| Health endpoint shape | R-10 |
| Artifact serving | R-11 |
| Seed DuckDB strategy | R-12 |
| Config defaults | R-13 |

No `NEEDS CLARIFICATION` markers remain. Phase 1 contracts
encode these decisions.
