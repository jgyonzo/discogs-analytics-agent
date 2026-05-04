# Feature Specification: Agent Schema Context Enrichment

**Feature Branch**: `005-agent-schema-context`
**Created**: 2026-05-01
**Status**: Draft
**Input**: User description: "take into consideration the most recent context of this conversation to fix the specification of the agent and then actually fix the agent. A bug in the schema understanding was discovered"

## Background — the bug

While exercising the V1 agent (feature `004-agent-v1`), the user
asked: *"Show the evolution of Techno releases over time"*. The
agent classified the query as `simple`, generated valid (and
safety-passing) SQL, executed it cleanly, and produced a chart
HTML — but the chart was blank.

Root-cause diagnosis (recorded in this conversation):

- The generated SQL was
  `SELECT year, COUNT(DISTINCT release_id) FROM release_unique_view WHERE primary_genre = 'Techno' GROUP BY year`.
- In the published DuckDB, `primary_genre` ∈ {Rock, Electronic,
  Pop, Jazz, Folk/World/Country, Classical, Hip Hop, Funk/Soul,
  Latin, Reggae, Non-Music, Stage & Screen, Blues, Children's,
  Brass & Military}. **There is no row with `primary_genre = 'Techno'`.**
- "Techno" is a **`style`** value, and `style` lives only on
  `release_fact` (not on `release_unique_view`). The canonical
  query — already documented at
  `docs/discogs_etl_initial_spec.md:1728` — filters
  `WHERE style = 'Techno'` on `release_fact` and groups by
  `decade`.
- The reason the LLM made the wrong column choice is that the
  schema context the agent provides is **column names only** — no
  values, no semantic distinction between coarse `primary_genre`
  buckets and granular `style` values. Faced with "Techno" and
  two columns named `primary_genre` and `style`, the model
  guessed.

The bug is therefore not a code defect in any single node — the
SQL is valid, safety checks pass, the sandbox runs cleanly. The
defect is in the **schema-understanding surface** the agent
exposes to the LLM, plus the absence of a zero-row guardrail
that would have caught the empty result before rendering a
useless chart.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Style-vs-genre questions return correct, non-empty results (Priority: P1)

A user asks the agent any natural-language question about a
specific musical style (Techno, House, Drum n Bass, Ambient,
Trance, Dub, Garage, Disco, Acid Jazz, Funk, ...). The agent
generates SQL that filters on the **right column** (`style` on
`release_fact`, not `primary_genre`), executes it, and returns a
chart populated with actual data.

**Why this priority**: This is the bug that motivated the
feature. Without it, every style-keyed question — which is the
single most common kind of question for a music catalog — silently
returns a blank chart. Trust in the agent collapses on the first
real query.

**Independent Test**: Run a fixed list of 10 well-known styles as
queries against the agent; for each, assert
`row_count > 0`, `dataframe_preview` is non-empty, and the SQL
references `style = '<value>'` (not `primary_genre = '<value>'`).

**Acceptance Scenarios**:

1. **Given** the agent is up and the published DuckDB contains
   Techno releases, **When** the user submits *"Show the
   evolution of Techno releases over time"*, **Then** the
   response has `status = "succeeded"`, `row_count >= 6` (one
   per decade with releases), and the rendered chart is
   non-blank.
2. **Given** the same setup, **When** the user submits any of
   the 10 canonical style queries, **Then** all 10 return
   non-empty results (no blank charts).
3. **Given** the user asks about *"Electronic releases by
   decade"*, **Then** the agent correctly filters by
   `primary_genre = 'Electronic'` (because Electronic IS a
   primary_genre value), confirming the fix does not regress
   the genre-level path.

---

### User Story 2 — Trend/evolution questions prefer `decade` over `year` (Priority: P2)

When the user asks an "evolution over time" / "trend" / "history"
question without specifying granularity, the agent chooses
`decade` (which has values for ≥99% of releases) rather than
`year` (sparser and noisier at the tails). Users keep the
ability to ask for yearly granularity explicitly ("year by
year", "annual", "by year").

**Why this priority**: Decade is the conventional reporting grain
in the source spec (`docs/discogs_etl_initial_spec.md:1728`) and
produces visibly better charts. Choosing year on small samples
produces extreme spikes near the tails. Lower priority than US1
because charts with `year` still render data — just less
useful — whereas US1 produces empty charts.

**Independent Test**: Submit a list of "evolution over time"
queries, assert generated SQL uses `decade` unless the question
literally contains "year" / "annual" / "yearly".

**Acceptance Scenarios**:

1. **Given** the user asks *"Show the evolution of Techno
   releases over time"*, **Then** the SQL groups by `decade`.
2. **Given** the user asks *"Techno releases year by year since
   2000"*, **Then** the SQL groups by `year` with `year >= 2000`.

---

### User Story 3 — Empty result sets are surfaced clearly to the user (Priority: P2)

If, despite the schema-context improvements, the agent generates
SQL that legitimately returns zero rows (the user asked about a
style that doesn't exist, a country with no releases, a decade
out of range), the response surfaces *"no matching releases"*
with the SQL used and a one-line hint, instead of producing a
blank-chart artifact and `status = "succeeded"`.

**Why this priority**: A blank chart with `status: "succeeded"`
is the worst possible UX — it looks like the agent worked when
it didn't. A clear empty-result message lets the user
self-correct.

**Independent Test**: Submit a query for a style that doesn't
exist (e.g., "Show Polka releases over time"). Assert the
response status is `succeeded_empty` (or the agreed terminal
state), the body contains a "no matching releases" message, and
no blank chart artifact is published.

**Acceptance Scenarios**:

1. **Given** the user submits a query whose SQL returns zero
   rows, **When** the agent finishes execution, **Then** the
   response indicates an empty result, includes the SQL that ran,
   and does NOT render a chart-shaped artifact whose
   `dataframe_preview` is empty.

---

### User Story 4 — Schema sample values are visible to the LLM at planning time (Priority: P3)

The schema context the agent passes into the router, query
understanding, and code generator prompts includes top-N
distinct values for low-cardinality categorical columns
(`primary_genre`, `primary_format_group`, `decade`,
`country` top-20 by frequency, plus a sampled set of `style`
values). This makes the bug from US1 self-correcting in the
common case: when the model sees that "Techno" is not in
`primary_genre` but appears in the `style` sample, it routes
the filter correctly without needing extra prose hints.

**Why this priority**: This is the structural fix that addresses
the root cause. P3 (not P1) because a smaller textual hint
("Techno is a style, not a primary_genre") in the prompts would
cover the immediate case; this is the durable improvement that
prevents future variants of the same class of bug.

**Independent Test**: Inspect the schema-context payload that
each prompt-rendering function produces; assert it contains a
sampled-values block for each named column, and that the total
size is under the agreed token budget.

**Acceptance Scenarios**:

1. **Given** the agent has connected to the published DuckDB,
   **When** any prompt is rendered, **Then** the rendered
   prompt contains the 14 distinct `primary_genre` values, the
   distinct `primary_format_group` values, the distinct
   `decade` values, and a sample of representative `style`
   values.
2. **Given** the schema-context block has been enriched,
   **Then** the per-request token overhead added to each prompt
   stays under ~1200 tokens.

---

### Edge Cases

- The user asks about a name that is BOTH a style AND a primary
  genre value (e.g., the literal string "Pop") — the agent must
  prefer `primary_genre` (lower selectivity → broader match) and
  document the choice in the rationale, but should not silently
  combine both.
- The user asks for a style that doesn't exist in the catalog
  (e.g., "Polka"). Covered by US3.
- The user uses lowercase / different casing ("techno" vs
  "Techno"). The fix should not depend on case sensitivity —
  rely on the LLM and the actual data values to handle this; do
  NOT add a case-insensitive filter (that breaks the
  contract-pinned column semantics).
- The user asks about a style that exists in `style` but is
  attached to releases with `decade IS NULL`. The chart should
  still render the rows that DO have a decade and the response
  should disclose the dropped rows in the rationale.
- The agent encounters a value that the LLM hallucinated as a
  style (not present in the sample). Two-pass safety check
  cannot help here (the SQL is technically valid). The fix is
  the zero-row handler from US3.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The schema-context payload that the agent passes
  to the router, query-understanding, code-generator, and
  repair-code prompts MUST include, for every published table,
  the column list AND a sampled-values block for low-cardinality
  categorical columns.
- **FR-002**: The sampled-values block MUST include all 14
  distinct values of `primary_genre`, all distinct values of
  `primary_format_group` and `decade`, the top-20 `country`
  values by release count, and a representative sample of
  `style` values (top-50 by release count is a reasonable
  default).
- **FR-003**: The schema-context payload MUST include a one-line
  domain glossary stating: *"`primary_genre` is the coarse
  bucket (e.g., Electronic, Rock); `style` is the granular
  subgenre (e.g., Techno, House, Ambient). Filter by `style` on
  `release_fact` for subgenre questions; filter by
  `primary_genre` on `release_unique_view` only when the value
  literally appears in the primary_genre sample."*
- **FR-004**: The schema-context block size MUST stay under 600
  tokens (measured with the same tokenizer the LLM client uses).
  Sample sizes MUST be reduced if the budget is exceeded; an
  observability log entry MUST record any truncation.
- **FR-005**: For trend/evolution-over-time questions without
  explicit granularity, the query understanding plan MUST prefer
  `decade` over `year`. The code generator prompt MUST surface
  this preference. Users keep the ability to override by saying
  "year", "yearly", or "annual" in the question.
- **FR-006**: After the sandbox executes the generated code, the
  agent MUST detect zero-row results before rendering the
  response. Zero-row outcomes MUST surface as a distinct
  terminal state (e.g., `succeeded_empty`) with a body
  containing: the SQL that ran, a "no matching releases"
  message, and a one-line diagnostic hint that suggests checking
  whether the filter value is a `style` or a `primary_genre`.
- **FR-007**: The schema-context construction MUST be cached at
  agent startup (or per-process), NOT recomputed on every
  request. The cache key MUST include the published DuckDB
  manifest's `run_id` so a republished DB invalidates the cache.
- **FR-008**: A regression test suite MUST exist that submits
  the 10 canonical style queries through the full graph and
  asserts non-empty results. This test MUST run as part of the
  agent's existing pytest suite (no new top-level test runner).
- **FR-009**: The fix MUST NOT change the published DuckDB
  contract (`specs/001-discogs-etl/contracts/duckdb-schema.md`
  and `specs/003-masters-artists/contracts/duckdb-schema.md`
  remain authoritative and unchanged).
- **FR-010**: The fix MUST NOT relax existing safety checks
  (forbidden tables, two-pass SQL safety, sandbox restrictions
  in `specs/004-agent-v1/contracts/sql-safety.md` and
  `code-generation.md` remain in force).

### Key Entities

- **Schema Context**: The payload — already produced by
  `discogs_agent.duckdb_layer.schema.get_schema_context()` and
  consumed by every prompt-rendering function — that this
  feature ENRICHES with sample values, the domain glossary, and
  the decade-preference hint. Not a new entity; an extended
  one. The wire shape (dict with `tables`, `has_master_fact`)
  remains backwards-compatible with the current state schema.
- **Empty-Result Sentinel**: The new terminal state added in
  FR-006. Sits next to the existing
  `succeeded` / `failed_unsupported` / `failed_safety` terminal
  states.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 10 canonical style queries (Techno, House,
  Ambient, Drum n Bass, Trance, Dub, Garage, Disco, Acid Jazz,
  Funk) submitted to the agent ALL return `row_count > 0` and
  produce non-blank charts. Pre-fix this number is 0/10;
  post-fix this number is 10/10.
- **SC-002**: The blank-chart-with-status-succeeded class of
  bug — i.e., a response that claims success but ships an empty
  dataframe — drops to 0 occurrences in the regression suite
  and the smoke set.
- **SC-003**: The schema-context block added to each prompt
  remains under 1200 tokens for the published catalog; the agent
  logs a structured warning if a future schema would push it
  over budget.
- **SC-004**: All 45 existing unit tests in `agent/tests/` keep
  passing. The new regression suite for US1 / US3 adds at least
  10 new passing tests.
- **SC-005**: For "evolution / trend / history" questions
  without explicit yearly granularity, ≥90% of generated SQL
  groups by `decade` rather than `year`, measured on a
  20-question evaluation set.

## Assumptions

- The published DuckDB at `data/published/duckdb/discogs.duckdb`
  is the same authoritative artifact described by the Phase 1+
  contracts; nothing changes in the ETL component.
- The bug surfaces against the full-dump April 2026 catalog
  (where Techno has 80k–185k releases per decade) AND any
  smaller sample DB, because the column-name vs. column-values
  ambiguity is structural.
- The OpenAI provider remains the only LLM backend (per the
  scope decision recorded in `004-agent-v1/spec.md`); the JSON
  fence-stripping fix already landed on the `004-agent-v1`
  branch is in scope to keep.
- Multi-turn carry-over remains the "light contextual carry-over"
  variant from `004-agent-v1`; this feature does not touch
  carry-over semantics.
- This is an enhancement to feature `004-agent-v1` (Component
  B), NOT a re-architecture. The graph nodes, retry policy, and
  Postgres schema (`specs/004-agent-v1/contracts/postgres-schema.md`)
  remain unchanged unless adding the new terminal state from
  FR-006 requires a column addition (in which case it is an
  additive migration).
- The agent's existing observability (`agent_run_log`,
  `agent_node_log`, `agent_cost_log`) is sufficient to verify
  SC-001/-002/-005; no new telemetry tables are added.

## Out of Scope

- A provider-agnostic LLM abstraction (still future work, per
  `004-agent-v1`).
- Carry-over across SQL/code (light user-text-only carry-over
  remains).
- Adding new published-surface columns or tables. The fix lives
  entirely in the agent component.
- Changing the chart-renderer / artifact format.
- Indexing / DuckDB physical layout changes.
- A semantic search over schema (e.g., embeddings of column
  documentation). Out of scope for this iteration; the
  sample-values + glossary approach is sufficient.
