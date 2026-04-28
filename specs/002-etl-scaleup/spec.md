# Feature Specification: Discogs ETL — Fase 2+3 (Real-data robustness + laptop-scale)

**Feature Branch**: `002-etl-scaleup`
**Created**: 2026-04-26
**Status**: Draft (clarifications resolved)
**Component**: `etl/` (per Constitution Principle VI — local laptop runtime)
**Builds on**: `specs/001-discogs-etl/` (Fase 1 — sample vertical slice, shipped)
**Source**: User description
"I want to continue with the next phases of the etl development. We
already implemented the first one called Fase 1, refer to
@docs/discogs_etl_initial_spec.md and the current etl specs and
artifacts in @specs/001-discogs-etl/ for context."

---

## Scope at a glance

Fase 1 delivered the sample-to-DuckDB vertical slice: 7 curated
releases, 54 passing tests, the published v1 analytics surface, and
all the contracts (CLI, manifest, DuckDB schema). This spec covers
the next two phases from `docs/discogs_etl_initial_spec.md`:

- **Fase 2 — Real-data robustness**: take the same pipeline and prove
  it survives a real Discogs releases excerpt (the
  `releases_sample_raw.xml` already in the repo — 404 real releases,
  truncated mid-element at line 10000) without crashes, with
  anomalies recorded as warnings.
- **Fase 3 — Laptop-scale full-dump execution**: run the pipeline
  against the full Discogs releases dump (~30M releases,
  ~60 GB XML, distributed as `.xml.gz`) on a developer laptop with
  bounded memory and observable progress.

**No contract changes.** Schemas, table names, naming conventions,
manifest top-level shape, CLI shape, and DuckDB published surface
remain exactly as Fase 1 ratified them. This spec is purely about
robustness, scale, and observability.

Fase 4 (masters / artists), Fase 5 (Discogs auto-downloader), and the
agent component remain explicitly out of scope. They will get their
own specs.

---

## User Scenarios & Testing *(mandatory)*

The "user" of this ETL is still the developer building the analytics
agent. The two new user stories describe what they need beyond the
sample slice.

### User Story 1 — Real-data robustness on a 404-release real sample (Priority: P1) — MVP increment

The developer can run the pipeline against
`etl/tests/fixtures/releases_sample_raw.xml` (a real 404-release
Discogs excerpt, intentionally truncated mid-element) and get a
clean run: no uncaught exceptions, no `quality_checks.status =
"incomplete"` caused by parser-side errors, and any anomalies
(truncation, unmapped format names, malformed dates, etc.) surfaced
as warnings in the manifest.

**Why this priority**: It's the smallest deliverable that proves the
Fase 1 pipeline survives real Discogs data, not just hand-crafted
fixtures. Without this, Fase 3's scale claim has no foundation.

**Independent Test**: Place `releases_sample_raw.xml` at the
configured raw path. Run the CLI's full-pipeline command. Verify the
run completes with `quality_checks.status ∈ {passed,
passed_with_warnings}` (NOT `incomplete`), the manifest records the
truncation and any unmapped values as warnings, and the published
DuckDB contains exactly the count of releases the parser
successfully extracted.

**Acceptance Scenarios**:

1. **Given** the truncated 404-release real sample at the raw path,
   **When** the developer runs the full pipeline, **Then** the run
   completes with exit 0, `quality_checks.status` is
   `"passed_with_warnings"`, and the manifest's
   `quality_checks.warnings` array contains an entry naming the
   truncation (e.g., `"parse_releases.truncated_xml"` with the byte
   offset or last successful release id).
2. **Given** the same input, **When** the developer queries the
   published DuckDB, **Then** `COUNT(DISTINCT release_id) FROM
   release_fact = 404` (the count of fully-formed releases — i.e.,
   the truncation is reported, not silently treated as 405).
3. **Given** any non-ASCII text in `releases_sample_raw.xml`
   (e.g., the `33 ⅓ RPM` description observed in release id=1),
   **When** the developer queries
   `release_fact.format_description_summary`, **Then** the value
   round-trips intact (no mojibake, no encoding errors during
   parse / write / read).
4. **Given** an unmapped `format name` is observed (raw sample
   contains only Vinyl / CD / Cassette, but synthetic edge cases
   may be added), **When** the run completes, **Then** the
   manifest's `quality_checks.warnings` array names the
   `normalize_release_entities.unmapped_format_names` entry and
   `clean_release_formats.format_group` is `"Other"` for those
   rows.

---

### User Story 2 — Laptop-scale execution on a real ~50k-release subset (Priority: P2)

The developer can run the pipeline against
`etl/tests/fixtures/releases_sample_big_raw.xml` — a real-data
subset of the Discogs releases dump containing the head 1,000,000
lines (~49,689 fully-formed releases, 191 MB uncompressed XML,
truncated mid-element at the end like the small raw sample). Inputs
may arrive as `releases.xml.gz` too (canonical Discogs distribution
form). The run processes streaming, with peak RSS bounded at a
configurable cap (default 4 GiB), progress visible during execution,
per-step durations / row counts / peak RSS in the manifest, and the
published DuckDB at the canonical path.

A complementary synthetic stress test exercises the parser over a
generated input large enough to exceed the bounded-memory check
threshold (FR-014 / `limits.dq_check_in_memory_threshold`,
configurable for tests) so that the SQL-based DQ implementations
are demonstrably exercised, even though the real subset is smaller
than that threshold.

**Why this priority**: This is the scale target that makes the
project meaningful. P2 not P1 because (a) without US1 it can't be
trusted on real data, and (b) US1 is what unblocks the agent
component, which can be developed in parallel against a smaller
DuckDB while US2 is being validated.

**Independent Test**: Place
`etl/tests/fixtures/releases_sample_big_raw.xml` at the configured
raw path (or a gzipped equivalent). Run the full pipeline. Observe:
peak RSS stays under the cap, progress log lines arrive at the
configured cadence (default every 10000 releases — so ~5 lines for
this input), the run completes, the manifest records per-step
durations / row counts / peak RSS, and the DuckDB at the canonical
path passes
`SELECT COUNT(DISTINCT release_id) FROM release_fact = 49689`
(modulo any rows dropped for missing `release_id`, surfaced as
warnings).

**Acceptance Scenarios**:

1. **Given** `releases_sample_big_raw.xml` at the raw path, **When**
   the developer runs the full pipeline, **Then** the run completes
   with exit 0 and `quality_checks.status =
   "passed_with_warnings"` (the truncation surfaces as a warning,
   per FR-001/FR-002), and
   `COUNT(DISTINCT release_id) FROM release_fact` equals the count
   of fully-formed `<release>` elements in the input
   (≈49,689 ± any dropped for empty `id`).
2. **Given** the same input gzipped to
   `releases.xml.gz`, **When** the developer runs the full
   pipeline, **Then** the parser streams directly from the gzipped
   file (no manual decompression), the run completes without
   out-of-memory errors, and the produced analytics Parquet is
   byte-identical to a parallel uncompressed run modulo
   `parsed_at`, `run_id`, and `source_file` fields.
3. **Given** any pipeline run, **When** the developer inspects the
   log during execution, **Then** progress messages are emitted at
   least every `log_progress_every` releases (default 10000) with
   a count and an elapsed-time field, both for the parse step and
   for any other step that processes per-release.
4. **Given** the run, **When** the developer reads the manifest
   after completion, **Then** every step has a non-null
   `step_durations[step_name]` entry and an informational
   `peak_rss_bytes` recorded under
   `step_metrics.{step_name}.peak_rss_bytes` (or equivalent).
5. **Given** the run on a developer laptop with the configured RSS
   cap, **When** the run completes, **Then** the process's peak
   RSS (measured at finalize_manifest) is below the cap. Exceeding
   the cap is recorded as a manifest warning, not an automatic
   failure.
6. **Given** the synthetic stress test (a generated input or a
   lowered `dq_check_in_memory_threshold` so SQL paths are
   exercised at fixture scale), **When** the test runs, **Then**
   the SQL-based DQ checks return the same `CheckResult` shapes as
   the in-memory implementations and the existing 54 Fase 1 unit
   tests still pass unchanged.

---

### Edge Cases

#### Real-data variability (Fase 2)

- The XML stream ends mid-element (truncated). → Parser stops
  cleanly after the last fully-formed release, emits a warning with
  the last successful `release_id`, and the run continues. Without
  this, lxml.iterparse raises `XMLSyntaxError` and the run finalizes
  as `incomplete`.
- A `<release>` has `id=""` (empty attribute). → Treated the same as
  missing `id`: dropped at staging, warning recorded, run continues.
- A text field contains characters outside the basic ASCII range
  (Unicode, emoji, special punctuation). → Round-trips via UTF-8
  through Parquet and DuckDB unchanged.
- A `<notes>` field contains many embedded newlines and is several
  KB long. → Persisted as a single TEXT column value; no truncation.
- A `<release>` has malformed nested elements (e.g.,
  `<id>not-a-number</id>`). → The malformed numeric is normalized
  to NULL (existing `clean_int` behavior); the rest of the release
  is preserved.
- The same `format name` appears with a different case
  (`"VINYL"`, `"Vinyl"`). → Mapping is case-insensitive (existing
  behavior).
- An integer attribute (e.g., `<format qty="...">`) parses as a
  Python int but exceeds the destination column's pyarrow type
  width — real Discogs data contains both legitimate-but-large
  values (5 × 10⁹, 10¹⁰) and clear typos (60-digit integer
  literals). → Values that fit in int64 are stored as-is; values
  that exceed even int64 are stored as NULL with a manifest
  warning (`normalize_release_entities.format_quantity_overflow`).
  The run continues. *(Retroactively added after a real-data
  full-dump surfaced this case during Fase 4 implementation;
  fixed in commit `2e6461a`.)*

#### Scale (Fase 3)

- Input is `.xml.gz`. → Streaming decompression; the parser reads
  through the gzip layer without a full-file extract.
- A `quality_checks` Counter-based check would need to materialize
  ~30M release ids in memory. → Re-implemented via DuckDB SQL
  aggregates so memory stays bounded.
- The pipeline takes hours to complete. → Progress logs continue
  to flow at cadence; the manifest is saved after every step so a
  Ctrl-C / OOM-kill leaves an inspectable
  `quality_checks.status = "incomplete"`.
- The full-dump run produces a DuckDB that is several GB. → The
  atomic-rename publish still writes to a `.new` sibling on the
  same filesystem and renames at the end; no contract change.

## Requirements *(mandatory)*

### Functional Requirements

#### Real-data robustness (Fase 2)

- **FR-001**: The releases parser MUST recover gracefully from a
  truncated or otherwise malformed XML stream after at least one
  fully-formed `<release>` element has been emitted. Recovery means:
  emit no further releases, do NOT raise to the runner, and surface
  a manifest warning naming the failure
  (`parse_releases.truncated_xml` or equivalent) with enough context
  (last successful `release_id` and/or byte offset) for the
  developer to diagnose.
- **FR-002**: A truncated input MUST yield
  `quality_checks.status = "passed_with_warnings"` (assuming all
  critical checks otherwise pass), NOT `"incomplete"`. The CLI exit
  code MUST be 0 in this case.
- **FR-003**: All text fields MUST be persisted as UTF-8 through
  Parquet (clean / staging / analytics) and DuckDB. No re-encoding,
  no character substitution, no silent truncation.
- **FR-004**: The pipeline MUST run end-to-end against
  `etl/tests/fixtures/releases_sample_raw.xml` (the 404-release
  real Discogs excerpt already in the repo) with all DQ checks
  classified as critical in Fase 1 still passing. New edge cases
  discovered while running it MUST be added to either the curated
  fixture or a new fixture, and the integration test MUST exercise
  the full pipeline against the new evidence.
- **FR-005**: Any `<release>` element with an empty or malformed
  `id` attribute MUST be dropped at staging (existing behavior),
  with the count of dropped rows surfaced as a manifest warning.
- **FR-006**: When a numeric staging attribute (notably
  `format_qty_raw`) parses as an integer too large for the
  destination column's pyarrow type, the pipeline MUST persist
  the cell as NULL and surface the count via a manifest warning
  (`normalize_release_entities.format_quantity_overflow` for the
  `format_quantity` case). The run MUST NOT crash. The schema
  choice MAY be widened (e.g., int32 → int64) when the widening
  is strictly permissive — every previously-valid value still
  fits — so FR-018 / FR-021 (no breaking changes to existing
  published tables) remain satisfied. *(Retroactively added
  after a real-data full-dump surfaced this case during Fase 4
  implementation; fixed in commit `2e6461a`.)*

#### Laptop-scale execution (Fase 3)

- **FR-010**: The pipeline MUST accept gzipped input at
  `data/raw/discogs/{snapshot_id}/releases.xml.gz`. Detection by
  filename suffix is sufficient. Decompression MUST be streaming —
  the pipeline MUST NOT extract the full file to disk before
  parsing. If both `releases.xml` and `releases.xml.gz` exist, the
  uncompressed file takes precedence (and a warning is recorded).
- **FR-011**: The pipeline MUST process the input in genuinely
  streaming fashion at full-dump scale — peak RSS MUST stay below
  a configurable cap (default `limits.peak_rss_cap_gib = 4`) for
  inputs of any practical size up to and including the full
  Discogs releases dump.
- **FR-012**: The parse_releases and normalize_* steps MUST emit
  progress log lines at the configured cadence
  (`limits.log_progress_every`, default 10000). Each progress line
  MUST include: step name, releases processed so far, elapsed
  seconds since step start, and instantaneous releases/sec.
- **FR-013**: The manifest MUST record, per step, an informational
  `peak_rss_bytes` field (under `step_metrics.{step_name}` or as
  an additional field on the existing `step_durations` entry —
  precise placement to be fixed in the plan / `contracts/manifest.md`
  update). Exceeding the cap is recorded as a manifest warning
  (`"runtime.peak_rss_exceeds_cap"`) but does NOT by itself fail
  the run — it is informational evidence that the bounded-memory
  invariant has been violated for that input.
- **FR-014**: DQ checks whose Fase 1 implementation materializes
  full columns into Python collections (Counter-based uniqueness,
  set-based distinct counts) MUST be re-implemented for layers
  whose row count can exceed
  `limits.dq_check_in_memory_threshold` (default 10_000_000). The
  bounded-memory implementation MUST return the same `CheckResult`
  contract; the existing tests MUST pass unchanged.
- **FR-015**: The `release_unique_view` correctness check (i.e.,
  `COUNT(*) over view == COUNT(DISTINCT release_id) over
  release_fact == row_count(clean_releases)`) MUST hold at full
  scale. This is already a critical DQ check in Fase 1; it just
  needs to remain tractable.

#### Cross-cutting

- **FR-020**: The CLI surface (`run`, `step`, flags) MUST NOT
  change in a backwards-incompatible way. Adding a new flag is
  allowed only if it is strictly optional with a sensible default.
  Existing scripts must keep working.
- **FR-021**: The published DuckDB schema MUST NOT change. No new
  columns, no new tables, no renamed columns, no type changes
  relative to Fase 1's `contracts/duckdb-schema.md`. Schema changes
  are a MAJOR contract change and require a constitution amendment.
- **FR-022**: The manifest schema MAY add new optional fields
  under `step_metrics` and / or `quality_checks.warnings`. It MUST
  NOT change types of existing fields or remove existing fields.
  New fields MUST be documented in an updated
  `contracts/manifest.md` in the same change set.

### Key Entities

Same as Fase 1 (Snapshot, Run, Release, Manifest). New entity
introduced here:

- **Step metrics** *(new)* — per-step peak RSS, releases-per-second,
  and any future runtime telemetry. Lives under
  `manifest.step_metrics.{step_name}` (additive over the Fase 1
  manifest contract).

## Success Criteria *(mandatory)*

### Measurable Outcomes

#### Fase 2 — Real-data robustness

- **SC-001**: The pipeline runs end-to-end on
  `releases_sample_raw.xml` (404 real releases, truncated) with
  exit status 0 and `quality_checks.status =
  "passed_with_warnings"`. The DuckDB published in this run
  contains exactly 404 distinct `release_id` values.
- **SC-002**: The integration test suite exercises the real raw
  fixture as part of CI; new test cases cover at least the
  truncation, the Unicode round-trip, and the empty-`id` edge case.
- **SC-003**: All 54 Fase 1 tests still pass unchanged. Coverage:
  100% (no test is removed or relaxed).

#### Fase 3 — Laptop-scale

- **SC-010**: The pipeline accepts a gzipped `releases.xml.gz` and
  produces the same outputs as it would for the equivalent
  uncompressed file (verified by running the small fixture through
  both forms and asserting byte-identical analytics Parquet,
  modulo `parsed_at` and `run_id`).
- **SC-011**: A run against
  `etl/tests/fixtures/releases_sample_big_raw.xml` shows peak RSS
  staying under the configured cap (default 4 GiB) across the run.
  Recorded in the manifest as
  `step_metrics.parse_releases.peak_rss_bytes` and verifiable
  externally with `/usr/bin/time -l` (macOS) or `/usr/bin/time -v`
  (Linux). Target peak RSS for the 191 MB / ~49,689-release input
  is comfortably under 1 GiB.
- **SC-012**: Progress log lines arrive at the configured cadence
  during long-running steps. Verifiable by grepping the run log
  for `progress` entries and confirming the count is approximately
  `total_releases / log_progress_every`.
- **SC-013**: The big-raw run completes and produces a DuckDB at
  the canonical path with `COUNT(DISTINCT release_id) FROM
  release_fact = 49689` (modulo any rows dropped for missing /
  empty `release_id`, reported as manifest warnings).
- **SC-014**: A synthetic stress test (a generated XML input large
  enough to cross
  `limits.dq_check_in_memory_threshold` configured for tests, or a
  lowered threshold) demonstrates that the SQL-based DQ check
  implementations are exercised and return the same `CheckResult`
  shapes as the in-memory ones. Pass criteria: the test asserts
  identical pass/severity/details fields for the same synthetic
  input under both code paths.

## Assumptions

- **Component scope**: This spec covers the `etl/` component only.
  Constitution Principle VI; same as Fase 1.
- **Phase scope**: Fase 2 (real-data robustness) AND Fase 3
  (laptop-scale) bundled in this spec, per Q1=B. Fase 4
  (masters/artists), Fase 5 (Discogs auto-downloader), and the
  agent component remain out of scope.
- **No contract changes**: Published DuckDB schema, CLI surface,
  manifest top-level shape, and naming conventions remain as
  Fase 1 ratified them. New fields under `step_metrics` are
  additive.
- **Real raw fixture (Fase 2)**:
  `etl/tests/fixtures/releases_sample_raw.xml` (404 real releases,
  intentionally truncated at line 10000) is the primary acceptance
  surface for Fase 2. New fixtures may be added for
  newly-discovered edge cases.
- **Real subset fixture (Fase 3)**:
  `etl/tests/fixtures/releases_sample_big_raw.xml` (the head
  1,000,000 lines of a real Discogs releases dump = ~49,689
  fully-formed releases, 191 MB uncompressed XML, truncated mid
  element) is the Fase 3 acceptance surface, per Q2=B. Plus a
  synthetic stress test to exercise SQL-based DQ paths.
- **Big fixture in git (decision deferred to plan)**: at 191 MB
  the big_raw fixture is large for a normal git commit. The plan
  phase decides whether to (a) commit it directly, (b) commit via
  Git LFS, or (c) keep it gitignored as a developer-local artifact
  with download/build instructions in the plan / quickstart.
  Recommended: option (c) for the first cut to keep clone-time
  fast; revisit if CI needs to run US2's integration test.
- **Implementation detail freedom**: The plan may swap
  `lxml.iterparse(... events=("end",), tag="release")` for
  `iterparse(..., recover=True)` or wrap it in a try/except as
  needed for FR-001; may reimplement DQ checks in DuckDB SQL for
  FR-014. These are plan-level decisions, not spec-level.
- **No external services**: The ETL still runs purely on the
  developer's laptop. No network, no cloud, no auto-download.

## Clarification History

The questions below were surfaced during initial drafting and
resolved before this spec left Draft.

| Question | Topic | Selected option |
|----------|-------|-----------------|
| Q1 | Phase scope of this spec | **B** — Fase 2 + Fase 3 bundled. Fase 4 / Fase 5 / agent each get their own spec. |
| Q2 | Fase 3 acceptance evidence | **B (with concrete fixture)** — a real run against `etl/tests/fixtures/releases_sample_big_raw.xml` (head 1,000,000 lines of the real dump = ~49,689 fully-formed releases, 191 MB) plus a synthetic stress test to exercise SQL-based DQ check paths. |

These resolutions are encoded in: the Scope-at-a-glance section,
US2 (acceptance scenarios reference the big_raw file), SC-011 /
SC-013 / SC-014, and the Assumptions section.
