# Feature Specification: Discogs Conversational Analytics Agent — V1

**Feature Branch**: `004-agent-v1`
**Created**: 2026-04-25
**Status**: Draft
**Input**: User description: "now lets start with the specification of the agent module. I've provided an initial spec in @docs/discogs_agent_initial_spec.md to start working on"

## Summary

This is the V1 of **Component B** under Constitution Principle VI
(`Two Components, One Contract`): a conversational analytics agent
that answers natural-language analytical questions about the Discogs
catalog by reading the published DuckDB produced by the ETL.

The agent receives a question, classifies it, generates Python code
with embedded read-only SQL, executes that code in a restricted
sandbox, validates the resulting interactive chart, and returns a
natural-language reply plus a chart artifact. Every run is
persisted (threads, runs, tool calls, model usage, artifacts,
errors) so an operator can audit what happened. The whole stack is
runnable locally via Docker Compose; AWS deployment is future work.

The agent is the second of the two components defined in
Constitution Principle VI. It MUST consume only the published
DuckDB surface (`release_fact`, `release_unique_view`,
`release_artist_bridge`, `release_label_bridge`, optional
`master_fact`); it MUST NOT touch raw XML, staging Parquet, or
clean Parquet at query time.

The canonical design source for this spec is
[`docs/discogs_agent_initial_spec.md`](../../docs/discogs_agent_initial_spec.md).
That doc enumerates the framework-level decisions (LangGraph for
orchestration, FastAPI for the API, Postgres for persistence,
Plotly HTML as the chart format, restricted subprocess as the V1
sandbox). Those decisions are inherited as scope and recorded
under **Assumptions** below; this spec captures the *behavior* the
agent must deliver.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Ask an analytical question and get an answer with a chart (Priority: P1)

A user (the demo evaluator) submits a natural-language question
about the Discogs catalog (e.g., "Show Techno releases by decade"
or "Which labels have the most stylistic diversity?"). They
receive a concise textual answer, a reference to an interactive
chart artifact, and the SQL that produced the result. When the
question can't be answered against the available data — because
it references a metric the catalog doesn't carry, or it's
genuinely ambiguous, or the generated code fails to produce a
valid result even after retries — they receive a controlled,
explanatory response instead of a crash or a stack trace.

**Why this priority**: This is the entire point of the agent.
Without it, the project has no demo; with just this story
working, there is already a viable MVP that exercises every
required graph node, every required tool, and the data contract
to the ETL.

**Independent Test**: Given a published DuckDB and a running
agent, send a known-good question via the public API and observe
that (a) a chart artifact file is produced, (b) the response
contains the SQL and a non-empty preview, and (c) running an
unsupported question returns a coherent explanation rather than
a 500. The chart is openable in a browser and shows the expected
shape.

**Acceptance Scenarios**:

1. **Given** a published DuckDB with `release_unique_view` and
   `release_fact` populated, **When** the user submits "Show the
   evolution of Techno releases over time", **Then** the
   response includes a generated SQL statement, a non-empty
   preview dataframe, a reference to a chart artifact (HTML),
   and a short natural-language summary; **And** running the
   same query again succeeds (no destructive side effect on the
   DuckDB).
2. **Given** the same DuckDB, **When** the user submits "Which
   labels have the most stylistic diversity?" (a complex query
   requiring joins and `COUNT(DISTINCT)`), **Then** the agent
   routes the query to the stronger model tier, produces SQL
   that joins `release_label_bridge` and `release_fact`, and
   returns a top-N chart of label-style diversity.
3. **Given** the same DuckDB, **When** the user submits "What
   is the average price of Techno releases?", **Then** the
   agent classifies the question as **unsupported**, does not
   generate or execute code, and returns a response explaining
   that price is not part of the published catalog and listing
   what *is* available.
4. **Given** the same DuckDB, **When** the user submits "Show
   me the best labels", **Then** the agent classifies the
   question as **clarification needed**, does not generate
   code, and returns a response asking the user to specify a
   metric (e.g., release count, distinct styles, distinct
   artists).
5. **Given** the same DuckDB, **When** the code generator
   produces code whose embedded SQL references a forbidden
   table or operation, **Then** the safety checker blocks it,
   the agent re-prompts the generator up to the configured
   retry budget, and only then either returns a successful
   chart or a controlled "could not safely answer" response —
   at no point does forbidden SQL run against the DuckDB.
6. **Given** the same DuckDB, **When** the generated code
   raises at runtime or exceeds the sandbox time budget,
   **Then** the agent retries (within the retry budget) and,
   if still failing, returns a controlled failure response
   that names the failure mode without exposing a raw
   traceback.
7. **Given** a published DuckDB that **lacks** `master_fact`,
   **When** the user submits "Which works have the most
   versions?" (a `master_fact`-only query), **Then** the agent
   reports that this question depends on data not present in
   the current snapshot, without crashing; **And** all queries
   that only need `release_fact` / `release_unique_view` /
   `release_artist_bridge` / `release_label_bridge` continue
   to work normally.

---

### User Story 2 — Run the whole agent stack locally (Priority: P2)

An operator (the same evaluator, or a code reviewer) clones the
repo, drops a published DuckDB into the configured location,
provides their model API key, and runs a single command to
bring up the full agent stack — the API service and its
persistence store. Within a short bounded time the API is
healthy and answering queries.

**Why this priority**: A first-rate analytical answer is
worthless if a reviewer can't actually run the thing.
Constitution Principle VI commits the agent to be containerized;
for V1 the practical form of that is "boots cleanly under
Docker Compose on a developer laptop". This is a load-bearing
capability for the demo.

**Independent Test**: From a clean checkout, run the documented
single-command boot, wait for health to flip green, and submit
a known-good query. The query must succeed end-to-end without
any manual intervention beyond providing the API key and the
DuckDB.

**Acceptance Scenarios**:

1. **Given** a clean checkout, a `.env` with a model API key,
   and a published DuckDB at the configured path, **When** the
   operator runs the documented "bring up the stack" command,
   **Then** the API service comes up, the persistence store
   comes up, and the health endpoint reports OK (DuckDB
   reachable, persistence reachable) within a documented time
   budget.
2. **Given** the stack is up, **When** the operator submits the
   golden demo query against the running API, **Then** they
   get a response with a chart artifact reference and can open
   the artifact in a browser.
3. **Given** the stack is up, **When** the operator stops it
   and restarts it, **Then** previously persisted runs and
   threads are still queryable (persistence is durable across
   restarts).
4. **Given** the published DuckDB is **missing** at startup,
   **When** the operator hits the health endpoint, **Then** it
   reports the missing-DuckDB condition (not OK), and `/query`
   returns a controlled service-unavailable response rather
   than crashing.

---

### User Story 3 — Inspect what happened on any prior run (Priority: P2)

An operator wants to understand a specific past run — what
route the question took, which model was selected, which tools
were called, what SQL was generated, what code ran, how many
tokens were used, and whether the run succeeded. They look this
up by `run_id` (or by `thread_id` for the parent grouping).

**Why this priority**: Trace transparency is what distinguishes
this project from a black-box "ChatGPT plugin". Constitution
Principle III (reproducibility / manifest) extends naturally to
the agent: every run's decisions must be inspectable. This
makes debugging and grading possible.

**Independent Test**: Submit a query, capture the returned
`run_id`, and then GET that `run_id` from the inspection
endpoint. The response must include the route classification,
the generated SQL, the tool-call timeline, the model-usage
breakdown, and the run status — enough to reconstruct what the
agent did without re-running it.

**Acceptance Scenarios**:

1. **Given** a successfully completed run, **When** the
   operator fetches that run by `run_id`, **Then** the response
   includes the original user query, the route decision, the
   generated SQL, the tool-call timeline (tool name, input,
   output, duration, status), the model-usage records (model,
   prompt tokens, completion tokens, estimated cost), the
   artifact reference, and the final response text.
2. **Given** a thread that has had multiple runs, **When** the
   operator fetches that thread by `thread_id`, **Then** the
   response lists those runs in order with their statuses,
   queries, and artifact references.
3. **Given** a run that ended in controlled failure (retries
   exhausted, unsupported question, etc.), **When** the
   operator fetches it, **Then** the response records the
   failure mode and the recorded errors (without exposing raw
   tracebacks to end-users; admin/debug consumers may see
   them).
4. **Given** a run that produced a chart, **When** the operator
   fetches that artifact by `artifact_id`, **Then** the agent
   serves (or links to) the chart file.

---

### User Story 4 — Continue a prior conversation (Priority: P3)

A user submits a follow-up question against a previously-used
`thread_id` (e.g., "now compare that to House"). The agent
groups this run under the existing thread so its trace shows
the conversation history.

**Why this priority**: Multi-turn is part of the canonical
design's stated capability and is the natural way to use a
conversational agent, but a useful demo is possible without it
(US1 + US2 + US3 cover the core deliverable). Hence P3.

**Independent Test**: Submit two queries against the same
`thread_id` and verify both runs are grouped under it in the
inspection endpoint and that the second query's run executes
successfully.

**Acceptance Scenarios**:

1. **Given** a prior run completed under `thread_id = T`,
   **When** the user submits a new query with the same
   `thread_id`, **Then** the new run is created under that
   same thread and is visible in `GET /threads/{T}` alongside
   the prior run.
2. **Given** no `thread_id` is supplied on `/query`, **When**
   the agent processes the query, **Then** a new thread is
   created and its `thread_id` is returned in the response.

---

### Edge Cases

- **Question references a metric/column that does not exist
  in the published DuckDB** (e.g., price, rating, user count)
  → classified as **unsupported**; no code generated;
  controlled response listing what is available.
- **Question is ambiguous** ("best labels", "important
  genres") → classified as **clarification needed**; no code
  generated; response asks the user to pick a concrete metric.
- **Generated SQL violates the allowlist** (forbidden table,
  forbidden statement, file-access function) → safety checker
  blocks it before execution; the generator is re-prompted
  with the violation; if the retry budget is exhausted with
  no safe SQL, the agent returns a controlled "could not
  safely answer" response.
- **Generated code raises a runtime exception** in the
  sandbox → captured as an error on the run; the validator
  triggers a repair pass within the retry budget; if
  exhausted, controlled failure response.
- **Generated code does not produce a `RESULT` object or a
  chart file** in the artifact directory → validator marks
  the run invalid, triggers a repair pass within the retry
  budget; if exhausted, controlled failure response.
- **Generated code exceeds the sandbox time budget** →
  sandbox terminates the subprocess; treated as an execution
  error and routed through the same retry/repair path.
- **Generated code attempts to write outside the run's
  artifact directory** or to make a network call → blocked
  by the sandbox restrictions; treated as a safety failure
  on the run.
- **Generated SQL uses `COUNT(*)` against `release_fact`**
  when the user actually wants distinct release counts (i.e.,
  silently row-multiplied by style) → the prompts and schema
  context enforce the count rule; the generator is expected
  to use `COUNT(DISTINCT release_id)` or
  `release_unique_view`. If a generated query does not, this
  is a correctness bug caught by the golden-query suite.
- **Published DuckDB is missing the optional `master_fact`**
  at startup → the schema reader detects its absence; the
  agent reports `master_fact`-only queries as unsupported
  for *this* snapshot but answers all release-grain queries
  normally.
- **Published DuckDB file is missing entirely** at startup →
  `/health` reports the missing-DuckDB condition; `/query`
  returns a controlled service-unavailable response; no
  generation or execution is attempted.
- **Persistence store is unavailable** at startup → `/health`
  reports the persistence condition; `/query` either returns
  service-unavailable or, if the implementation supports it,
  proceeds without persistence and reports that on the run —
  the *exact* fallback is a plan-level decision, but a clean
  health signal is required either way.
- **Two queries land on the same thread concurrently** → V1
  runs each query as an independent sequential run within the
  thread; concurrent multi-run interleaving on a single
  thread is out of scope for V1.
- **A `master_fact`-dependent query is asked and the snapshot
  has it** → answered normally (e.g., "Which works have the
  most versions?" → `master_fact ORDER BY release_count
  DESC`).

## Requirements *(mandatory)*

### Functional Requirements

#### Conversational analytics flow

- **FR-001**: The agent MUST accept a natural-language analytical
  question via a public HTTP API and return, in a single
  response, all of: a `thread_id`, a `run_id`, a
  natural-language reply, a reference to the generated chart
  artifact (when one was produced), the SQL that was executed
  (when one was executed), and a route summary indicating the
  complexity classification.
- **FR-002**: The agent MUST classify each question into
  exactly one of: **simple**, **complex**, **unsupported**,
  **clarification needed**. The classification MUST be
  persisted with the run.
- **FR-003**: For **unsupported** questions the agent MUST NOT
  generate or execute code; it MUST return a controlled
  response that names what data is missing and lists what is
  available.
- **FR-004**: For **clarification needed** questions the agent
  MUST NOT generate or execute code; it MUST return a response
  that asks the user for the specific missing dimension/metric.
- **FR-005**: For **simple** and **complex** questions the
  agent MUST proceed to generate executable code, route through
  the safety check, the sandbox, and the chart validator, and
  return either a successful chart-bearing response or a
  controlled failure response — never an opaque crash.
- **FR-006**: The orchestration layer MUST be a deterministic
  multi-step graph (not a free-form ReAct loop) with explicit
  transitions and explicit terminal states. The graph MUST
  have at least four named decision/processing steps and at
  least one retry edge that can route a failed validation back
  to code generation.
- **FR-007**: The agent MUST select between two model tiers —
  a cheaper tier for simple questions and a stronger tier for
  complex questions — based on the classification from FR-002.
  The selected tier MUST be persisted with the run. The
  underlying LLM provider for both tiers is **OpenAI**: the
  cheap tier MUST default to `gpt-4o-mini` and the strong
  tier MUST default to `gpt-4o`, both configurable via the
  `CHEAP_MODEL` and `STRONG_MODEL` env vars; credentials MUST
  be supplied via `OPENAI_API_KEY`.

#### Data-contract enforcement

- **FR-008**: The agent MUST consume only the analytical
  DuckDB produced by the ETL, at a configurable path. It MUST
  connect in read-only mode for every query. It MUST NOT
  modify the DuckDB during any run.
- **FR-009**: The agent MUST allowlist the queryable surface
  to exactly: `release_fact`, `release_unique_view`,
  `release_artist_bridge`, `release_label_bridge`, and the
  optional `master_fact`. Generated SQL referencing any other
  table/view (notably `stg_*`, `clean_*`,
  `release_format_summary`) MUST be blocked before execution.
- **FR-010**: The agent MUST NOT read raw Discogs XML, staging
  Parquet, or clean Parquet at query time. It MUST NOT import
  code from the ETL package (Constitution Principle VI).
- **FR-011**: The agent MUST detect at startup (and refresh as
  appropriate) whether the optional `master_fact` is present
  and adapt routing accordingly: questions that depend on it
  MUST be answerable when present and MUST be classified as
  unsupported-for-this-snapshot when absent — without
  crashing.
- **FR-012**: The agent MUST encode and enforce the
  `release_fact` count rule: counting unique releases MUST go
  through `COUNT(DISTINCT release_id)` or
  `release_unique_view`, never `COUNT(*) FROM release_fact`
  unless the user explicitly wants to count release-style
  rows. This rule MUST be present in the prompt context
  given to the generator and MUST be exercised in the
  golden-query test suite.

#### SQL safety

- **FR-013**: Generated SQL MUST be allowed to use only
  `SELECT` and `WITH` constructs against allowlisted
  tables/views. The safety checker MUST block, before
  execution: data-modifying statements (`INSERT`, `UPDATE`,
  `DELETE`, `DROP`, `ALTER`, `CREATE`, `COPY`, `EXPORT`,
  `INSTALL`, `LOAD`, `ATTACH`, `DETACH`); file-access
  functions (`read_csv`, `read_parquet`, `read_json`, `glob`,
  anything httpfs/S3); and any reference to a non-allowlisted
  table/view.
- **FR-014**: When the safety checker blocks generated SQL,
  the agent MUST attempt repair by re-prompting the generator
  with the violation. After a configurable retry budget the
  agent MUST stop and return a controlled "could not safely
  answer" response. At no point may forbidden SQL execute
  against the DuckDB.

#### Code execution safety

- **FR-015**: Generated Python MUST execute in a restricted
  sandbox that enforces: a hard time budget, a deny-list on
  network access, no package installation at runtime, and a
  per-run write directory restricted to a designated
  artifacts path under `{thread_id}/{run_id}`. Writes
  outside that directory MUST be prevented or treated as
  failures.
- **FR-016**: The sandbox MUST capture and persist stdout,
  stderr, exit code, exception, and execution duration for
  every code execution attempt.
- **FR-017**: Generated code MUST produce a structured result
  object containing at minimum: the executed SQL, the chart
  artifact path, a small dataframe preview, and the row
  count. Missing or malformed result objects MUST be treated
  as validation failures.

#### Chart artifacts

- **FR-018**: A successful run MUST produce exactly one chart
  artifact per run, persisted as a self-contained interactive
  HTML file under `{ARTIFACTS_DIR}/{thread_id}/{run_id}/`.
  Artifact metadata (id, run_id, thread_id, type, path,
  created_at) MUST be persisted alongside.
- **FR-019**: The chart validator MUST verify, for every
  successful execution, that: the artifact file exists at
  the declared path, the file has the expected extension,
  and the result-object preview is structurally valid (a
  non-zero-row table or a documented empty-result case).
  Validation failures MUST trigger the retry path within the
  retry budget.

#### Persistence and traceability

- **FR-020**: Every conversation MUST be assigned a
  `thread_id`; every individual question MUST be assigned a
  `run_id`; both MUST be persisted in a durable store. The
  store MUST survive process restarts.
- **FR-021**: For every run the agent MUST persist: the user
  query, the route decision, the generated SQL, the run
  status (succeeded / failed / unsupported /
  clarification-needed), start and finish timestamps, total
  latency, and the final response text.
- **FR-022**: For every tool invocation made during a run the
  agent MUST persist: the tool name, the node that invoked
  it, the input payload, the output payload, the status, the
  latency, and any error message. At least five distinct
  tool types MUST be exercised across the agent's flow.
- **FR-023**: For every model invocation made during a run
  the agent MUST persist: the model name, the prompt and
  completion token counts, the estimated cost, the latency,
  and the invoking node.
- **FR-024**: For every error encountered during a run the
  agent MUST persist: the error type, the error message, the
  invoking node, and (in admin/debug-only views) the
  traceback. End-user responses MUST NOT expose raw
  tracebacks.

#### Inspection API

- **FR-025**: The agent MUST expose an inspection endpoint by
  `run_id` that returns the route, the generated SQL, the
  tool-call timeline, the model-usage records, the persisted
  errors, the artifact references, and the final response —
  enough to reconstruct what the run did without re-running
  it.
- **FR-026**: The agent MUST expose an inspection endpoint by
  `thread_id` that lists the runs grouped under that thread,
  in chronological order, with each run's status, query, and
  primary artifact reference.
- **FR-027**: The agent MUST expose an artifact-fetch
  endpoint that resolves an `artifact_id` to its underlying
  chart file (or a link/redirect to it).

#### Local operability

- **FR-028**: The agent MUST be runnable locally as a
  containerized stack consisting of, at minimum, the API
  service and its persistence store, brought up by a single
  documented command from a clean checkout.
- **FR-029**: The DuckDB MUST be mountable into the agent
  container as read-only; the artifacts directory MUST be
  mountable as read-write; the persistence store's data
  volume MUST persist across restarts.
- **FR-030**: The agent MUST expose a health endpoint that
  reports, separately, whether the DuckDB is reachable and
  whether the persistence store is reachable, and that
  returns OK only when both conditions hold.
- **FR-031**: All operational secrets (model API keys,
  database passwords) MUST be supplied via environment / a
  gitignored `.env` file at runtime — never committed
  (Constitution: Secrets).

#### Multi-turn (P3)

- **FR-032**: A request to `/query` that supplies an existing
  `thread_id` MUST attach the new run to that thread. A
  request without `thread_id` MUST create a new thread and
  return its id. When a thread is reused, the agent MUST
  inject a **light contextual carry-over** into the new run's
  `query_understanding` prompt: the *user-query text* of the
  prior runs in that thread (not their generated SQL, not
  their generated Python, not their dataframe previews) MUST
  be summarized into the prompt so that follow-up phrasings
  (e.g., "now compare that to House") resolve against the
  prior turn's intent. The carry-over MUST be bounded (a
  documented cap on number of prior turns and total token
  budget) and MUST be visible in the persisted prompt
  context for traceability. SQL/code carry-over and full
  contextual replanning are out of scope for V1.

#### Component independence

- **FR-033**: The agent MUST live under its own top-level
  directory with its own dependency manifest (Constitution
  Principle VI). Cross-imports between the ETL package and
  the agent package are forbidden in V1.

### Resolved scope decisions

These two questions were surfaced as open clarifications
during spec authoring and resolved by the user before
planning:

- **Model tier provider (FR-007 / FR-031)** → **OpenAI**, per
  the canonical doc's default. Cheap tier defaults to
  `gpt-4o-mini`, strong tier to `gpt-4o`; both are
  env-configurable (`CHEAP_MODEL` / `STRONG_MODEL`).
  Credentials are supplied via `OPENAI_API_KEY` in a
  gitignored `.env`. A provider-agnostic interface is
  explicit future work.
- **Multi-turn depth (FR-032)** → **light contextual
  carry-over**. Prior-run *user-query text* (only) is
  summarized into the new run's `query_understanding`
  prompt, bounded by a documented turns/token cap. Generated
  SQL and generated Python from prior runs are **not**
  carried over in V1. Full contextual replanning is explicit
  future work.

### Key Entities *(include if feature involves data)*

- **Thread**: a logical grouping of runs that share a
  conversational context. Has an id, timestamps, status, and
  metadata.
- **Run**: a single user-question → response cycle. Belongs
  to exactly one thread. Records the user query, the route
  decision (complexity, selected model), status, timestamps,
  total latency, and the final response text.
- **ToolCall**: a single invocation of a named tool by a
  named graph node within a run. Records inputs, outputs,
  status, latency, and any error.
- **ModelUsage**: a single LLM invocation within a run.
  Records the invoking node, model name, token counts,
  estimated cost, and latency.
- **Artifact**: a generated chart file produced by a run.
  Records the run_id, thread_id, type (e.g., "plotly_html"),
  filesystem path, metadata, and creation time.
- **Error**: a recorded failure during a run. Records the
  run, invoking node, error type, message, traceback
  (admin/debug only).
- **AgentState**: the in-memory graph state for an active
  run (user query, schema context, route, plan, generated
  code, generated SQL, safety result, execution result,
  validation result, artifact paths, dataframe preview,
  retry counter, errors, final response). Not persisted as a
  row but its derived fields are persisted via the entities
  above.
- **SchemaContext**: the read-only view of the published
  DuckDB the agent observes at startup — table/view names,
  columns with types, and the boolean "is `master_fact`
  present" flag — used to ground prompts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean checkout, a reviewer who has the
  published DuckDB and a model API key can bring the stack
  up, hit `/health` and see OK, and submit a known-good
  query that returns a chart artifact, in under **15
  minutes** of hands-on time (excluding image-build time on
  first boot).
- **SC-002**: For a documented set of **at least 6 golden
  demo questions** (covering simple-trend, format
  comparison, label-diversity, outlier detection, and an
  optional `master_fact` question), the agent succeeds —
  produces a valid chart artifact and a non-empty preview —
  on **at least 5 of 6** when run against a snapshot known
  to contain the relevant data.
- **SC-003**: For a documented set of negative-path questions
  (one unsupported, one ambiguous, one that triggers a
  safety-checker block, one that triggers a sandbox failure),
  the agent returns a controlled, non-crashing response on
  **100%** of runs — no opaque 500s, no leaked tracebacks
  to the end-user response.
- **SC-004**: Across the test suite, **every distinct
  routing outcome** (supported simple, supported complex,
  unsupported, clarification needed) and **every retry
  edge** (safety retry, validation retry, retries-exhausted
  controlled failure) is exercised by at least one path
  test.
- **SC-005**: For every successful run, the inspection
  endpoint returns a record that contains all of: route,
  generated SQL, at least one tool call entry, at least one
  model usage entry, the final response — verifiable on
  **100%** of test runs.
- **SC-006**: At least **five distinct tool types** are
  invoked across the documented golden runs, and each is
  visible in the persisted tool-call records (verifying the
  ≥5-tools requirement).
- **SC-007**: Repeated runs against the same DuckDB and the
  same query produce a chart artifact every time (within the
  retry budget); no run mutates the DuckDB file
  (byte-equality check before/after a documented batch of
  test queries).
- **SC-008**: The agent answers the **`release_fact` count
  rule** correctly: for the golden query "Show Techno
  releases over time", the resulting SQL uses
  `COUNT(DISTINCT release_id)` (or `release_unique_view`),
  not `COUNT(*) FROM release_fact`. Verified by a
  golden-query test that asserts on the persisted SQL.
- **SC-009**: Persistence survives a full stack restart: a
  run created before bringing the stack down is still
  retrievable via the inspection endpoint after a fresh
  bring-up against the same volumes — verified by an
  integration test.
- **SC-010**: A typical simple query, end-to-end on a warm
  stack against the curated demo DuckDB, returns its chart
  in under **30 seconds** wall-clock at the P50 (and the
  hard sandbox time budget is documented and enforced).

## Assumptions

This spec inherits the framework-level scope decisions made
in the canonical design doc
[`docs/discogs_agent_initial_spec.md`](../../docs/discogs_agent_initial_spec.md).
Those decisions are scope, not implementation details
deferable to the plan; they are recorded here so the
specification is self-contained.

- **Orchestration**: a LangGraph-based deterministic
  StateGraph organizes the run, with named nodes for schema
  loading, routing, query understanding, code generation,
  SQL safety, sandboxed execution, chart validation, and
  response synthesis. (Section 8 of the canonical doc.)
- **API surface**: a FastAPI HTTP service from V1 — `POST
  /query`, `GET /threads/{thread_id}`, `GET /runs/{run_id}`,
  `GET /artifacts/{artifact_id}`, `GET /health`. (Section
  15.)
- **Persistence store**: Postgres (rather than SQLite or
  files), running alongside the API as a sibling container.
  (Sections 6.2 and 14.)
- **Chart format**: Plotly HTML, written as a single
  self-contained `.html` per run, suitable for
  later-frontend rendering. (Section 6.7.)
- **Sandbox**: a restricted in-host subprocess (not a
  separate sandbox-worker container) for V1, with the time
  budget, env restriction, and artifact-path scoping noted
  in FR-015. A separate sandbox-worker container is future
  work. (Section 6.3.)
- **Tools as local Python**: tools are implemented as local
  Python objects integrated into the LangGraph graph, not
  as MCP servers. (Section 6.4.) MCP exposure is future
  work.
- **No RAG in V1**: schema context is injected directly into
  prompts; there is no retrieval layer. (Section 6.5.)
- **Local-only deployment in V1**: AWS deployment is
  explicitly future work. Constitution Principle VI defers
  the AWS service choice to a follow-up amendment, and
  this spec does not bind it.
- **Demo dataset**: integration tests ship a small seed
  DuckDB fixture under `agent/tests/fixtures/` (analogous
  to the ETL's `releases_sample.xml` etc.) so they don't
  require a full ETL run; end-to-end / smoke tests against
  a real ETL-produced DuckDB are also expected, as a
  separate layer.
- **Phasing**: this spec covers V1 end-to-end (the canonical
  doc's six implementation phases — skeleton through demo
  readiness — are scope, not separate specs). The work is
  large but coherent; splitting at the spec level was
  considered and rejected in favor of one spec mirroring
  the doc's scope, then leaving `/speckit-tasks` to break it
  down into the actual delivery slices.
- **Authentication**: the V1 API is unauthenticated — V1
  is local-only and academic, per the canonical doc's
  non-goals.
- **Concurrency**: V1 targets a single-developer demo.
  Heavy concurrent traffic, multi-tenant isolation, and
  queueing are out of scope.
- **Discogs DuckDB origin**: the agent assumes the
  published DuckDB at the configured path was produced by
  an earlier ETL run conforming to specs 001/002/003. The
  agent does not validate the DuckDB beyond reading the
  allowlisted tables/views.
- **LLM provider (resolved 2026-04-25)**: V1 uses **OpenAI**
  for both model tiers (cheap = `gpt-4o-mini`, strong =
  `gpt-4o`, both env-configurable). A provider-agnostic
  abstraction is future work.
- **Thread resumption (resolved 2026-04-25)**: V1 implements
  **light contextual carry-over** — only the user-query text
  of prior runs in the same thread is summarized into the
  new run's `query_understanding` prompt, with a documented
  cap on turns and tokens. Prior generated SQL/code is not
  carried over.
