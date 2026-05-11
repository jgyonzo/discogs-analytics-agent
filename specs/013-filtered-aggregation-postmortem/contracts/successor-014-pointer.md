# Successor pointer: future ETL-component spec (`014-release-unique-view-materialization`)

**Source feature**: `013-filtered-aggregation-postmortem`
**Status**: deferred work — pointer only, no implementation in 013.
**Target component**: `etl/` (NOT `agent/` — Principle VI separation).

This document records the deferred ETL-side fix that would resolve the root cause of every `release_unique_view`-induced sandbox OOM-kill. 013 ships agent-layer workarounds (glossary tightening + observability) because the root cause cannot be fixed without crossing the component boundary, and 013's user direction explicitly scoped to `agent/` only.

---

## The deferred problem

`release_unique_view` is defined (in ETL) as:

```sql
CREATE OR REPLACE VIEW release_unique_view AS
SELECT DISTINCT
  release_id, master_id, title, primary_artist_id, primary_artist_name,
  country, released_raw, year, month, day, released_date,
  released_date_precision, decade, data_quality, track_count,
  artist_count, label_count, genre_count, style_count, format_count,
  primary_label_id, primary_label_name, primary_format_raw,
  primary_format_group, format_quantity, format_description_summary,
  has_vinyl, has_cd, has_cassette, has_digital, has_box_set,
  primary_genre, run_id
FROM release_fact;
```

(Exact column list varies by ETL version; the structural pattern is `SELECT DISTINCT (~33 columns) FROM release_fact`.)

Every query against the view triggers DuckDB to materialize the full deduplicated 19M × 33 set before any downstream operation. Predicate pushdown through the DISTINCT is NOT performed by DuckDB's planner in the general case, so even queries with selective WHERE clauses on joined tables (e.g., the Depeche Mode case) force the full materialization and typically OOM the sandbox.

The 012 + 013 mitigations work *around* the view (steering the agent toward `release_fact` + `COUNT(DISTINCT release_id)` for count-shaped questions). They do not *fix* it. Three query classes remain partially unanswerable until the view is rewritten:

1. **SUM / AVG / MIN / MAX of release-grain numerics** (e.g., "average track_count per decade"). On `release_fact` the answer is style-weighted (wrong); on the view, the materialization OOMs.
2. **Existence/boolean filters at release grain** (e.g., "releases with vinyl from Germany"). Same trade-off.
3. **Spot-checks** are fine on the view today and would remain fine after any of the suggested fixes.

---

## Suggested implementation directions for the future spec

Three viable approaches. The future spec author should evaluate against current ETL constraints (Principle II's bounded-memory mandate, Principle III's reproducibility).

### Option A: Materialize the view as a real table

Replace the `CREATE VIEW` with a `CREATE TABLE … AS SELECT DISTINCT ON (release_id) …` (or DuckDB's equivalent). Built once during the ETL's analytics-layer assembly. Trade-offs:

- **Pro**: Every read against the table is now O(scan), no per-query DISTINCT. The view's nominal value proposition (canonical release-grain surface) is recovered for all three load-bearing query classes.
- **Pro**: Storage footprint is bounded — one row per release, ~33 cols × 19M rows ≈ 5–8 GiB depending on column widths and compression. Acceptable.
- **Con**: Doubles the storage on the analytics layer (the table + the underlying `release_fact`). Mitigated by Parquet+compression on the analytics-layer intermediate.
- **Con**: An ETL-side change requires a published-DuckDB rebuild (Principle I contract-change).

### Option B: Drop the view entirely, replace with per-attribute summary tables

Build separate small tables for each release-grain attribute family (`release_format_summary`, `release_genre_summary`, etc.). Eliminates the omnibus 33-column DISTINCT.

- **Pro**: Each table is small, focused, indexable.
- **Pro**: Aligns with Principle V's "surface minimalism" intent.
- **Con**: More tables on the agent-facing surface. Each new table is a new place for the LLM to hallucinate join shapes.
- **Con**: More invasive ETL rewrite; touches multiple analytics-layer producers.

### Option C: Redefine the view without the 33-column DISTINCT

Use `SELECT DISTINCT ON (release_id) …` (Postgres-flavor; DuckDB supports `QUALIFY ROW_NUMBER() OVER (PARTITION BY release_id) = 1` as an equivalent). The view becomes a window-function pick rather than a multi-column DISTINCT.

- **Pro**: Smallest diff. Same column shape, same agent-facing API.
- **Pro**: Window functions are typically cheaper than multi-column DISTINCT in DuckDB.
- **Con**: Still a view (computed each query); does not eliminate the per-query cost — only reduces it. May still OOM at full-catalog scale.
- **Con**: `DISTINCT ON` chooses arbitrary winners across the duplicate-removing columns; semantics differ subtly from the existing `SELECT DISTINCT *` (which requires every column to match). Edge cases may show different rows.

**Recommendation**: Option A. Cleanest semantics, best operational profile, modest storage cost. Option C is the cheapest diff but doesn't fully solve the problem. Option B is most architecturally pure but most disruptive.

---

## Acceptance criterion for `014` to close 013's lingering gap

A single benchmark question MUST succeed within the sandbox memory budget:

> *Average track_count by decade across the full catalog.*

Expected SQL (post-014):

```sql
SELECT decade, AVG(track_count) AS avg_tracks
FROM release_unique_view
GROUP BY decade
ORDER BY decade;
```

This query is the canonical SUM/AVG-over-release-numerics shape that 013 cannot answer at catalog scale (per `data-model.md` Edge Cases). After 014 lands with Option A or Option C, this query MUST return without OOM.

When the benchmark passes, 013's glossary entry #3 SHOULD be loosened in a subsequent amendment to permit `release_unique_view` in JOIN/GROUP BY again. Until then, the tightening remains in force.

---

## Component-boundary respect (Principle VI)

This pointer is recorded in 013 (`agent/`-component spec) but the work belongs to `etl/`. 013 does NOT cross the boundary. The future `014` spec, when opened, will:

- Live under `specs/014-release-unique-view-materialization/` (or whichever number is next available at that time).
- Touch `etl/` source files (e.g., the analytics-layer producer for `release_unique_view`).
- Update `specs/001-discogs-etl/contracts/duckdb-schema.md` (the view's definition contract).
- NOT touch `agent/` (the glossary loosening, if undertaken, would be a separate agent-side amendment).

---

## When NOT to open `014`

This deferral is acceptable indefinitely if:

1. The three load-bearing query classes (SUM/AVG-over-release-numerics, existence-at-release-grain, multi-attribute-aggregation-without-DISTINCT-pushdown) remain low-priority for the agent's curated demo set and real user traffic.
2. The agent-side workarounds (013's glossary tightening + 012's prompt steering) prove sufficient in production.
3. ETL maintenance budget is constrained.

If those conditions hold, `014` can be deprioritized indefinitely without compromising 013's correctness. The pointer remains in place as a record of "we knew, we chose to defer."

---

## Provisional naming and timing

- **Spec number**: `014-release-unique-view-materialization` (provisional; may be renumbered when actually opened depending on what other specs land first).
- **Trigger conditions to open it**:
  - A real user question hits the SUM/AVG-over-release-numerics class and produces an `oom_killed` event in production logs.
  - OR a planned demo includes such a question and 013's glossary tightening + memory-pressure hint is judged insufficient UX.
  - OR an ETL maintenance sprint is in flight and absorbing this change is cheap.
- **No timeline commitment from 013.** This is a "when the time comes" pointer, not a deadline.
