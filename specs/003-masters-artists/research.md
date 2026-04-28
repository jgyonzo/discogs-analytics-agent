# Phase 0 Research: Discogs ETL — Fase 4

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Purpose**: Resolve implementation decisions for the masters /
artists pipelines and the rich Q3=C `master_fact` build. No
remaining `[NEEDS CLARIFICATION]` markers from the spec — all three
were resolved before plan started.

Each entry: **Decision** — **Rationale** — **Alternatives considered**.

---

## R-01: Generalize the gzip-aware input opener

**Decision**: Refactor `etl/src/discogs_etl/io/input.py`. Rename the
existing `open_releases_input(snapshot_dir)` to a parameterized
helper `open_xml_input(snapshot_dir, basename)` that resolves
`{basename}.xml` vs `{basename}.xml.gz` with the same precedence
(uncompressed wins, gz_and_plain_present flag) as Fase 2+3. Provide
thin wrappers `open_releases_input(snapshot_dir)`,
`open_masters_input(snapshot_dir)`, `open_artists_input(snapshot_dir)`
that call the generalized helper for backwards-compat with existing
callers.

**Rationale**:
- Keeps the streaming gzip semantics exactly as Fase 3 ratified.
- One detection / precedence rule lives in one place — adding a new
  XML basename later is a one-line change.
- Wrappers preserve the existing call sites (`prepare_sources.py`,
  `releases_parser.py`) so the spec 002 implementation stays
  surface-stable.

**Alternatives considered**:
- Keep three independent functions with copy-pasted detection
  logic: noisier and harder to keep in sync.
- Drop the wrapper functions, change callers directly: bigger diff
  for no functional gain.

---

## R-02: Streaming parsers for masters and artists

**Decision**: Two new files mirror `releases_parser.py`:
- `parsers/masters_parser.py` exposing
  `class MasterStream(path, *, limit=None)` and
  `iter_masters(path, *, limit=None)`.
- `parsers/artists_parser.py` exposing
  `class ArtistStream(path, *, limit=None)` and
  `iter_artists(path, *, limit=None)`.

Both classes mirror `ReleaseStream` exactly: `__iter__` drives
`lxml.etree.iterparse(file_obj, events=("end",), tag=<root_tag>)`
inside `try / except etree.XMLSyntaxError`, captures
`truncation_info: TruncationInfo | None`, performs the
`elem.clear()` + walk-back-siblings pattern. Memory bound preserved
end-to-end.

**Rationale**:
- Three siblings is more readable than one parameterized stream
  class with a "record extractor" callback — each XML schema
  warrants its own purpose-built record extractor.
- The truncation-handling contract (FR-005) carries over verbatim.
- Reuse of the existing `_resolve_input` helper from
  `releases_parser.py` is tempting but coupling parsers makes the
  generalization in `io/input.py` (R-01) the single point of
  contact instead — each parser calls `open_*_input()` itself.

**Alternatives considered**:
- One generic `XmlElementStream(path, tag, extractor)`:
  abstract-but-unhelpful; the three extractor callables would each
  hold all the schema-specific code anyway.
- Keep the parser functions free (no class, just a generator like
  Fase 1's original): loses the post-iteration `truncation_info`
  attribute that Fase 2 introduced.

---

## R-03: Conditional execution of input-dependent steps

**Decision**: Steps that depend on optional XML inputs
(`parse_masters`, `parse_artists`, `normalize_masters`,
`normalize_artists`, `build_master_fact`) check input availability
inside `run()` and return early — emitting an informational log
line — when their input is missing. The runner's `Step` Protocol is
NOT extended.

The cascade is:
- `prepare_sources` calls `open_xml_input(...)` for each of
  releases / masters / artists. Releases is required (raises if
  missing — same as Fase 1+2+3 behavior). Masters / artists
  trigger `prepare_sources.masters_missing` /
  `prepare_sources.artists_missing` warnings on absence; no
  exception, no critical failure.
- `parse_masters.run()` opens via `open_masters_input(...)`; on
  `FileNotFoundError`, logs and returns. No staging output.
- `normalize_masters.run()` checks for
  `ctx.staging_dir / "stg_masters.parquet"`; if absent, logs and
  returns. No clean output.
- `build_master_fact.run()` checks for
  `ctx.clean_dir / "clean_masters.parquet"`; if absent, logs and
  returns. No analytics output.
- `publish_duckdb.run()` adds `master_fact` to the DuckDB only
  when `ctx.analytics_dir / "master_fact.parquet"` exists.

**Rationale**:
- No protocol change. The runner stays generic; conditional logic
  is local to each step.
- Cascades naturally: missing input → missing staging → missing
  clean → missing analytics → not in DuckDB. The manifest
  `outputs.*` blocks accurately reflect what was produced.
- The runner still records `step_durations` and `step_metrics` for
  the no-op case; that's correct (the step DID run, it just had
  nothing to do).

**Alternatives considered**:
- Add a `should_run(ctx) -> bool` method to the Step Protocol:
  cleaner separation but a Protocol change with downstream impact
  on the runner and every existing step. Not worth it for v1
  conditional logic.
- Make the runner aware of optional inputs via configuration:
  more configuration knobs, more failure modes.
- Use `outputs_exist` to fake "I'm done": misleading semantics —
  Fase 2's runner skips on `outputs_exist=True`, which would
  read as "outputs already cached" rather than "nothing to do".

---

## R-04: master_fact build — joining strategy

**Decision**: `build_master_fact` runs AFTER `build_release_fact`
(step ordering pinned in `cli.py`'s STEPS list and in tasks.md).
The build step uses an in-memory DuckDB connection
(`duckdb.connect(":memory:")`) with the same pattern as
`build_release_fact`. The query joins:

```sql
WITH master_universe AS (
    SELECT DISTINCT master_id FROM read_parquet('{clean_masters}')
    UNION
    SELECT DISTINCT master_id FROM read_parquet('{clean_releases}')
    WHERE master_id IS NOT NULL
),
master_meta AS (
    SELECT master_id, title, main_release_id, year, decade
    FROM read_parquet('{clean_masters}')
),
release_agg AS (
    SELECT master_id,
           COUNT(*)::INTEGER       AS release_count,
           MIN(year)::INTEGER      AS earliest_year,
           MAX(year)::INTEGER      AS latest_year
    FROM read_parquet('{clean_releases}')
    WHERE master_id IS NOT NULL
    GROUP BY 1
),
main_release_genre_style AS (
    SELECT release_id, primary_genre, style AS primary_style
    FROM read_parquet('{release_fact}')
    WHERE style_order = 1
)
SELECT
    u.master_id,
    m.title,
    m.main_release_id,
    m.year,
    m.decade,
    COALESCE(a.release_count, 0)::INTEGER AS release_count,
    a.earliest_year,
    a.latest_year,
    g.primary_genre,
    g.primary_style
FROM master_universe u
LEFT JOIN master_meta  m USING (master_id)
LEFT JOIN release_agg  a USING (master_id)
LEFT JOIN main_release_genre_style g
       ON g.release_id = m.main_release_id
ORDER BY u.master_id
```

**Rationale**:
- The `master_universe` CTE captures every master_id seen in
  EITHER `clean_masters` OR `clean_releases.master_id` so no id is
  silently dropped (FR-009).
- `release_count` defaults to 0 for orphan masters via COALESCE.
- `earliest_year` / `latest_year` are nullable when no releases
  reference the master — the LEFT JOIN to `release_agg` produces
  NULL there (FR-009 / SC-002).
- `primary_genre` / `primary_style` come from `release_fact` at
  `style_order = 1` (the primary style row); LEFT JOIN to
  `main_release_id` yields NULL when missing or unresolved
  (FR-009 / SC-004 / Edge Cases:
  `build_master_fact.main_release_unresolved`).
- DuckDB does the heavy lifting; Python emits dicts to
  `BatchedParquetWriter` with the `MASTER_FACT` schema.

**Alternatives considered**:
- Compute genre/style as the most common across the master's
  releases (mode + tie-break): harder, ambiguous, and Discogs's
  `main_release_id` is the canonical "primary edition" anyway.
- Materialize `release_unique_view` first: that view DOESN'T
  include `style` (because style is the row-multiplying axis of
  release_fact). We need `release_fact` directly for primary_style.
- Read `release_fact.parquet` from a different run (e.g., the
  prior published one): wrong — must use this run's release_fact
  for consistency with this run's master_fact.

---

## R-05: master_fact cross-table consistency check

**Decision**: A new check function
`_check_sum_equals_count_sql(master_fact_path, clean_releases_path,
*, name, layer, table_name)` is implemented as a standalone
SQL-only helper (no in-memory variant) because it spans two
parquet files. It runs:

```sql
SELECT
    (SELECT SUM(release_count) FROM read_parquet('{master_fact}')) AS sum_,
    (SELECT COUNT(*)            FROM read_parquet('{clean_releases}') WHERE master_id IS NOT NULL) AS cnt_
```

Returns `passed = (sum_ == cnt_)`, severity `critical` (per FR-015).
This is invoked from `run_analytics_checks` once `master_fact`
exists.

**Rationale**:
- The check is inherently cross-table; the
  single-parquet `dispatch.run_check` doesn't fit. A standalone
  helper is the cleanest match.
- "Always SQL" is acceptable because both parquet are O(1)
  cardinality at full-dump scale (master count + release count fit
  in DuckDB query result rows trivially).
- Parity test isn't needed (no in-memory sibling), but a
  unit test asserts pass/fail correctness for synthetic inputs.

**Alternatives considered**:
- Implement an in-memory variant for parity-pattern consistency:
  more code, no benefit at the scales involved.
- Make `dispatch.run_check` accept a list of paths: protocol
  expansion for one client.

---

## R-06: Year normalization for masters

**Decision**: Reuse the existing
`transforms/date_normalization.parse_released(raw)` from Fase 1.
For masters, the only meaningful precision is `year` (no month or
day in `<master><year>...</year>`). Map `parse_released` output to:
- `year` ← parsed year (or None)
- `decade` ← `(year // 10) * 10` (or None)
- `year_precision` ← `parsed.released_date_precision` if it's
  `year` / `unknown` / `invalid`; otherwise normalize ('day' /
  'month' shouldn't occur for master year_raw and will be
  collapsed to 'invalid' if observed).

`year_precision` becomes a column in `clean_masters` for parity
with `clean_releases.released_date_precision` (a similar enum).

**Rationale**:
- Zero new transform code. The existing `parse_released` is
  battle-tested by Fase 1's tests.
- `clean_masters.year_precision` mirrors
  `clean_releases.released_date_precision` semantics for
  cross-layer consistency.

**Alternatives considered**:
- Write a separate `parse_master_year(raw)`: duplicates logic that
  already exists. Not worth it.

---

## R-07: Artists parsing — what to capture, what to skip

**Decision**: For Fase 4 (Q1=B), `ArtistStream` captures only the
top-level fields documented in source spec §6.10:
`artist_id`, `artist_name`, `realname`, `profile`. Nested
`<aliases>` / `<groups>` / `<members>` / `<urls>` /
`<namevariations>` blocks are visited only enough to advance lxml's
parser cursor; their contents are NOT extracted in this spec.

**Rationale**:
- Q1=B: `artist_dim` is deferred. The clean_artists output only
  needs the `artist_id`, `artist_name`, `realname`, `profile`,
  `run_id` columns (matches §6.10 and FR-008).
- Capturing aliases/members/groups would expand `stg_artists`
  schema with bridge tables — that's the Q2=enriched path under a
  different Q1, which we explicitly didn't take.
- The future `artist_dim` spec is explicitly the right place to
  add nested-element parsing.

**Alternatives considered**:
- Capture nested elements now even though we don't use them:
  forward-compat at the cost of bloating staging, complicating DQ
  checks, and pre-committing to a schema before we know what the
  agent needs. Rejected.
- Skip `<profile>` since it's noisy long text: violates source
  spec §6.10's column list. The spec keeps it; the agent never
  sees it (no DuckDB surface).

---

## R-08: prepare_sources extension for masters/artists detection

**Decision**: Extend `steps/prepare_sources.py` to call
`open_xml_input(snapshot_dir, basename)` for each of `releases`,
`masters`, `artists`:
- Releases: required (raises `FileNotFoundError` like today).
- Masters / Artists: optional. On success → record source_file +
  hash; on `FileNotFoundError` → emit
  `prepare_sources.masters_missing` /
  `prepare_sources.artists_missing` warning, skip recording the
  source_file entry.

The `manifest.source_files` block grows from one key (`releases`)
to up to three (`releases`, `masters`, `artists`). All entries
have the same shape: `{path, size_bytes, checksum}`.

**Rationale**:
- Single point of detection. Downstream steps don't need to
  duplicate the missing-input warning emission.
- Manifest's `source_files` block stays the canonical record of
  what the run consumed.

**Alternatives considered**:
- Detect inside each parser step: duplicates logic and risks
  inconsistent warning emission.
- Add a CLI flag `--no-masters` / `--no-artists`: violates
  FR-017 (no CLI changes); auto-detection is simpler and less
  cognitive load.

---

## R-09: DuckDB publisher — conditional master_fact

**Decision**: `io/duckdb_publisher.publish(*, analytics_dir,
published_duckdb)` is updated:

```python
core_tables = {
    "release_fact":           analytics_dir / "release_fact.parquet",
    "release_artist_bridge":  analytics_dir / "release_artist_bridge.parquet",
    "release_label_bridge":   analytics_dir / "release_label_bridge.parquet",
}
optional_tables = {
    "master_fact": analytics_dir / "master_fact.parquet",
}
```

Core tables are always published (FileNotFoundError otherwise).
Optional tables are added only when their parquet exists. The
`release_unique_view` is always created on top of `release_fact`.
The atomic-rename pattern from Fase 1's `publish` stays unchanged.

**Rationale**:
- Conditional adds match FR-012 (no empty shells in DuckDB).
- Backward-compat: a release-only snapshot publishes the exact
  same DuckDB shape as Fase 2+3.
- The atomic-rename guarantee from Fase 1 still protects the
  canonical path on a failed run (FR-022 of spec 001).

**Alternatives considered**:
- Always create an empty `master_fact` table when input was
  missing: violates FR-012; agent would see a misleadingly empty
  table.
- Publish `master_fact` to a separate DuckDB file: complicates the
  agent's connection logic; rejected.

---

## R-10: Fixture strategy

**Decision**:

- **Real raw fixtures** (already committed by the user):
  - `etl/tests/fixtures/masters_sample_raw.xml` (664 KB, 317
    masters, truncated mid-element).
  - `etl/tests/fixtures/artists_sample_raw.xml` (3.7 MB, 4841
    artists, truncated mid-element).
  - These are the primary acceptance surface for parser
    truncation handling and for the
    `test_real_masters_artists_pipeline.py` integration test.

- **Curated small fixtures** (NEW, hand-crafted in this spec's
  tasks.md):
  - `etl/tests/fixtures/masters_sample.xml` (~5 entries) — covers:
    a master with `main_release_id` resolving to a release in the
    curated `releases_sample.xml`, a master with no
    `main_release_id`, a master with a non-parseable `<year>`, a
    master referenced by zero releases (orphan), a master with
    Unicode in `<title>`.
  - `etl/tests/fixtures/artists_sample.xml` (~5 entries) —
    covers: an artist with `realname`, an artist without
    `realname`, an artist with a long `<profile>`, an artist with
    Unicode in `<name>` / `<realname>`, an artist with empty
    `<id>` (drops with warning).
  - `etl/tests/fixtures/masters_sample_bad.xml` — duplicate
    `master_id` for the FR-022 failure-path coverage.

- **Cross-snapshot consistency**: the `releases_sample.xml`
  curated 7-release fixture should reference at least 2–3 of the
  master_ids from `masters_sample.xml` so the joining /
  primary_genre / primary_style derivations have real data to
  match. This may require a small edit to `releases_sample.xml`
  to add `<master_id>` elements pointing at the curated masters
  (the existing curated fixture has hand-crafted `master_id`
  values 9001..9007 — we'll align the curated masters_sample.xml
  to use those same ids for some entries).

**Rationale**:
- The hand-crafted small fixtures give predictable assertions for
  the integration test: exact `release_count`, exact
  `primary_genre`, exact `primary_style`.
- The real raw fixtures cover truncation handling and serve as
  the "this works on real data" smoke layer.
- Aligning master_ids across releases_sample.xml and
  masters_sample.xml is cheap (hand-edit a couple of entries) and
  makes the integration test's joins meaningful.

**Alternatives considered**:
- Generate the curated fixtures programmatically: bigger code,
  same outcome.
- Use only the real raw fixtures: hard to assert exact
  `release_count` numbers without running the entire pipeline by
  hand and reading off the values.

---

## Resolved spec clarifications (recap)

| Question | Answer | Encoded in |
|----------|--------|------------|
| Q1 — Scope of artist analytics | **B**: Build master_fact only; defer artist_dim. | spec.md scope-at-a-glance + Assumptions; this plan's Summary |
| Q2 — artist_dim richness | **N/A**: artist_dim not built. | spec.md Clarification History |
| Q3 — master_fact richness | **C**: metadata + counts + primary_genre + primary_style. | FR-009; this research's R-04 |

## Outcome

All implementation decisions made. No `[NEEDS CLARIFICATION]`
markers. Constitution Check still PASS. Phase 1 (data-model.md,
contracts/, quickstart.md) can proceed.
