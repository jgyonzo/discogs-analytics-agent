# Research: Agent Schema Context Enrichment

## R-1 — How to compute sample values without burning startup time

**Decision**: Use one DuckDB query per categorical column, with
`SELECT col, COUNT(*) AS c FROM tbl WHERE col IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT N`.
Run all of them once at agent startup, alongside the existing
`read_schema_context()` call.

**Rationale**: DuckDB scans `release_fact` (~22M rows) for a
single-column GROUP BY in well under a second on the local M-series
laptop the project targets. The full set of sample queries
(primary_genre, primary_format_group, decade, country, style) is
6 queries. Total cold-start cost stays under a few seconds — well
inside the agent-startup budget. Computing per-request would
multiply that cost on every query and is unnecessary because the
catalog is republished, not mutated in place.

**Alternatives considered**:
- *Per-request sampling* — rejected: same answer every time,
  wasted latency.
- *Pre-baking samples into a JSON file at ETL publish time* —
  attractive but couples the two components (ETL would need to
  know what the agent samples). Per Principle VI we keep them
  decoupled.
- *Embedding-based schema understanding (e.g., column docs in
  vector DB)* — overkill for 4 tables and ~600 styles. Out of
  scope per the spec.

## R-2 — Cache invalidation

**Decision**: Use the existing `_cache` module-level variable
in `duckdb_layer/schema.py`. Cache key is implicit (process-
local, single value). Invalidation is "process restart". A
`run_id` (read from `release_unique_view`'s `run_id` column) is
captured INTO the SchemaContext as `published_run_id` so callers
can detect mismatches if needed, but cache eviction is not
data-driven.

**Rationale**: The agent runs as a long-lived container; on
catalog republish the deploy procedure is to redeploy the agent
(or restart the container) anyway, since the bundled DuckDB or
mounted volume changes. A more sophisticated cache would add
complexity for no observed benefit.

**Alternatives considered**:
- *TTL-based cache* — fragile; caches stale schema across
  republish if the TTL hasn't expired.
- *Watch-the-file-mtime invalidation* — possible but couples
  agent code to filesystem semantics that vary by deploy target
  (mounted volume vs. baked-in image).

## R-3 — Token budget enforcement

**Decision**: Use a tiktoken-based count via the
`langchain_openai` tokenizer (already a transitive dep). At
`build_schema_context()` time, render the sample block as a
string and count tokens; if >600, drop the lowest-frequency
samples first (`country` first, then `style`) until under
budget. Log a structured warning if truncation happens.

**Rationale**: 600 tokens is small relative to the ~16k context
of `gpt-4o-mini`; this is about cost, not headroom. Ranking
truncation by sample frequency keeps the most useful values for
the model.

**Alternatives considered**:
- *Char-count proxy* (e.g., `len(s) / 4`) — fast but inaccurate
  near the boundary.
- *Skip enforcement entirely* — invisible cost growth with
  schema growth.

## R-4 — Where to detect zero-row results

**Decision**: In the `chart_validator` *tool*
(`agent/src/discogs_agent/tools/chart_validator.py`), which is
already the gate between sandbox execution and response
synthesis. Add a new validator outcome `reason="empty_result"`
that is *not* a failure — it's a successful execution that
returned no rows. The `chart_validator` *node* maps that to
`terminal_status="succeeded_empty"` and skips retry.

**Rationale**: The chart validator already inspects the
sandbox's `RESULT` dict (which contains `row_count` and
`dataframe_preview`). It already has the chart-existence check,
so adding a row-count check fits the same shape. Doing it
elsewhere — in the synthesizer, or in a brand-new node —
fragments the success/failure logic.

**Alternatives considered**:
- *Detect in `sandbox_executor`* — wrong layer; sandbox just
  runs code. Empty results are a query/answer concern, not an
  execution concern.
- *Detect in `response_synthesizer`* — the synthesizer would
  still need the row-count signal, so we'd be passing the same
  data through. Cleaner to set the terminal state earlier.
- *New graph node* — overkill; one line in chart_validator
  reads the row_count.

## R-5 — Postgres schema change

**Decision**: Add `succeeded_empty` to the `agent_runs.status`
CHECK constraint via a new Alembic migration:
`005_xx_add_succeeded_empty.py`. The migration drops the old
constraint and recreates it with the extended set. This is
additive: no existing rows have to change.

**Rationale**: The CHECK constraint pin at
`004-agent-v1/contracts/postgres-schema.md:49` enumerates the
valid values; we cannot just write the new value — Postgres
will reject it. An additive migration is the standard fix.
Operations: idempotent, runs in milliseconds, zero downtime
because the agent's running query is `INSERT/UPDATE` with a
status that's already in the allowlist.

**Alternatives considered**:
- *Encode the empty-result as `succeeded` + a body sub-status*
  — keeps the schema fixed but loses queryability ("show all
  empty-result runs in the last week" becomes a JSON-search,
  not an indexed lookup) and conflates two distinct outcomes.
- *Drop the CHECK constraint entirely and rely on application-
  level validation* — weakens the contract; future status
  values would silently land in the table.

## R-6 — Style sample selection

**Decision**: Top-50 styles by release count. Truncated to top-
30 if the token budget tightens.

**Rationale**: The catalog has ~600 distinct styles but the
distribution is heavily long-tail; the top-50 cover nearly all
of the queries a user will actually ask. Listing 600 would
blow the token budget; listing only 10 would miss niche-but-
real styles like "Acid Jazz" and "Drum n Bass". 50 is the
sweet spot validated empirically against the test set.

**Alternatives considered**:
- *All distinct styles* — token-budget-blowing.
- *Top-10* — misses common queries (Drum n Bass is #~20).
- *A semantic-search index* — out of scope per spec.

## R-7 — Decade vs. year preference signal

**Decision**: Add an explicit one-line hint to
`code_generator.md` and `query_understanding.md`: *"For
'evolution / over time / trend' questions WITHOUT explicit
yearly granularity, group by `decade`, not `year`. Override
only when the user says 'year', 'yearly', or 'annual'."*. No
code-level enforcement; this is a prompt-level nudge.

**Rationale**: The LLM responds well to small, specific
instructions. A code-level enforcement (post-hoc rewrite of
`year` to `decade`) would be brittle and break the user's
explicit asks for yearly granularity. The prompt hint is
reversible, transparent, and easy to validate via the SC-005
20-question evaluation set.

**Alternatives considered**:
- *Code-level rewrite* — brittle; high false-positive rate.
- *Train a small classifier on "evolution" intent* — overkill.

## R-8 — Testing strategy

**Decision**: Three tiers.
1. **Unit** (`agent/tests/unit/`) — mock DuckDB, assert that
   schema context contains the sample block, the glossary, and
   the size budget; assert chart_validator emits
   `succeeded_empty` when `row_count == 0`.
2. **Integration** (`agent/tests/integration/test_schema_context_real_duckdb.py`)
   — opens a small fixture DuckDB (the existing test fixture
   used by `004-agent-v1`), asserts real samples render.
3. **Golden** (`agent/tests/golden/test_canonical_styles.py`)
   — runs the 10 canonical style queries through the full
   graph against a minimal stub LLM that produces SQL using
   the (now-enriched) schema context. Asserts non-empty
   `dataframe_preview`. Must remain fast (< 5 s on CI).

**Rationale**: Three tiers mirror the existing test layout
(`unit/`, `integration/`, `golden/`) and keep CI signals
specific. The golden test is the regression guard that
directly validates SC-001.

**Alternatives considered**:
- *End-to-end test against a live OpenAI key* — costly and
  flaky for CI. Reserve for manual smoke runs.
- *Skip the integration tier* — leaves the real-DuckDB sample-
  block code untested.
