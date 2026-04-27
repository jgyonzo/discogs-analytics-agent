# Feature Specification: Discogs ETL — Fase 1 (Sample Vertical Slice)

**Feature Branch**: `001-discogs-etl`
**Created**: 2026-04-25
**Status**: Draft (clarifications resolved)
**Component**: `etl/` (per Constitution Principle VI — local laptop runtime)
**Source**: User description "I want to implement the solution described in
@docs/discogs_etl_initial_spec.md", with the linked document
`docs/discogs_etl_initial_spec.md` as the authoritative starting point.

## Scope at a glance

This spec covers **Fase 1 (minimal vertical slice on a sample)** of the
source document only. Real-world XML variability (Fase 2) and full-dump
scale on a laptop (Fase 3) are explicitly **deferred to follow-up specs**;
masters/artists XML parsing (Fase 4) and the Discogs downloader (Fase 5)
are likewise deferred. The deliverable here is the smallest end-to-end
slice from a curated releases-XML sample to a published DuckDB
containing the v1 analytics tables and view, with all v1 contracts in
place so follow-up specs only have to expand validation surface, not
redesign contracts.

---

## User Scenarios & Testing *(mandatory)*

The "user" of this ETL is the developer building this project's
analytics agent (Component `agent/`, future spec). The ETL has no human
end-user. Its job is to convert Discogs XML dumps into a stable DuckDB
analytics surface that the agent will query.

### User Story 1 — Sample-to-DuckDB vertical slice (Priority: P1) — MVP and entire scope of this spec

The developer can run a single command against a small, curated local
Discogs releases XML sample (a few hundred to a few thousand releases)
and get, on disk, the canonical published DuckDB containing
`release_fact`, `release_artist_bridge`, `release_label_bridge`, and the
`release_unique_view` view, plus a manifest describing the run.

**Why this priority**: This is the smallest end-to-end slice that
unblocks the analytics agent. Once a published DuckDB exists with the v1
contract, the agent component can be designed and prototyped in
parallel, even with sample data underneath. Without this slice, neither
component can advance.

**Independent Test**: Place a curated sample releases XML at the
configured raw path. Run the CLI's full-pipeline command. Verify that
`data/published/duckdb/discogs.duckdb` exists; that
`SELECT COUNT(DISTINCT release_id) FROM release_fact` matches the count
of `<release>` elements in the sample (modulo documented filtering on
malformed rows); that `data/manifests/{run_id}.json` exists with
non-empty `outputs` and a `quality_checks.status` of `passed` or
`passed_with_warnings`.

**Acceptance Scenarios**:

1. **Given** a curated sample releases XML at
   `data/raw/discogs/{snapshot_id}/releases.xml` and a base config,
   **When** the developer runs the full-pipeline CLI command,
   **Then** all of the following exist within the run's directories:
   staging Parquet for `releases / artists / labels / formats /
   format_descriptions / genres / styles / tracks`; clean Parquet for
   `releases / artists / labels / formats / genres / styles` plus
   `release_format_summary`; analytics Parquet for `release_fact /
   release_artist_bridge / release_label_bridge`; the published DuckDB;
   and a manifest file referencing all of them.
2. **Given** a successful run, **When** the developer opens the DuckDB
   and runs `SELECT * FROM release_fact LIMIT 10`, **Then** the column
   set matches the contract in source spec §9.1, and overall row count
   is ≥ the input release count (one row per `release × style`;
   releases with no style emit one row with `style_order = 0` and
   `style = NULL`).
3. **Given** a successful run, **When** the developer queries
   `release_unique_view`, **Then** `COUNT(*)` over the view equals
   `COUNT(DISTINCT release_id)` over `release_fact`, and equals the
   input release count.
4. **Given** a successful run, **When** the developer runs the agent's
   canonical example query
   (`SELECT decade, COUNT(DISTINCT release_id) AS releases FROM
   release_fact WHERE style = 'Techno' AND decade IS NOT NULL GROUP BY
   decade ORDER BY decade`) against the published DuckDB, **Then** the
   query returns one row per non-null decade for which Techno-styled
   releases exist in the sample.

---

### Edge Cases (in scope for Fase 1)

The cases below are part of *contract behavior* — even on a small
curated sample they are likely to occur, and the v1 contracts in the
source spec already specify the expected behavior. They are validated
in this spec.

- A release element appears in the XML but has no `release_id` →
  rejected at the staging contract boundary (`release_id NOT NULL`)
  and recorded as a warning with the offending element's source
  position; the run continues.
- A `released` field is `0000`, `Unknown`, empty, or otherwise not
  parseable → normalized to `released_date_precision = "unknown"` (or
  `"invalid"` if explicitly malformed) per source spec §11.1, with a
  warning recorded.
- A release has `country` empty or missing → allowed; `country` is
  nullable per the contract.
- A release has zero `<style>` elements → emits exactly one row in
  `release_fact` with `style = NULL` and `style_order = 0` per source
  spec §9.1.
- A release has zero `<format>` elements → produces a row in
  `release_format_summary` with `format_count = 0` and all `has_*`
  flags false; `release_fact` still has a row for the release.
- A `format_name_raw` is encountered that does not appear in the
  documented mapping table (source spec §11.2) → mapped to
  `format_group = "Other"` or `"Unknown"` and recorded as a warning so
  the mapping table can be extended.
- Duplicate label entries with identical
  `(release_id, label_id, label_name, catno)` → deduped in
  `clean_release_labels`; entries differing only on `catno` → both
  preserved (source spec §7.3 dedup rule).
- A re-run with the same `run_id` against existing outputs without
  `--force` → fails with a clear error and exit ≠ 0 before any layer
  is written.

The following classes of edge cases are *deferred*:

- Pipeline behavior under arbitrary, untested XML variability beyond
  the curated sample — covered by the follow-up Fase 2 spec.
- Gzip-compressed inputs, mid-run process termination, memory caps,
  per-step duration logging at scale — covered by the follow-up Fase 3
  spec.

## Requirements *(mandatory)*

### Functional Requirements

#### Pipeline shape

- **FR-001**: The system MUST organize processing as the layered
  pipeline defined in the constitution (Principle I): `raw` →
  `staging` → `clean` → `analytics` → `published` (DuckDB).
- **FR-002**: The system MUST expose a single CLI entrypoint to run
  the full pipeline end-to-end (`run`), and the same entrypoint MUST
  allow each individual step to be invoked independently
  (`step <step-name>`).
- **FR-003**: The CLI MUST accept these flags at minimum: `--config`,
  `--run-id`, `--snapshot-id`, `--limit-releases`, `--force`,
  `--skip-existing`. Semantics: `--limit-releases N` truncates input
  after the Nth `<release>` element; `--force` allows overwriting
  outputs at an existing `run_id`; `--skip-existing` causes a step to
  be skipped if all its declared outputs for the given `run_id`
  already exist on disk.

#### Inputs

- **FR-004**: The system MUST read Discogs releases XML from a local
  path under `data/raw/discogs/{snapshot_id}/releases.xml`.
  Auto-download from Discogs is OUT OF SCOPE. Gzip-compressed inputs
  are NOT a requirement of this spec (sample inputs may be assumed
  uncompressed).

#### Streaming and bounded memory

- **FR-005**: The releases parser MUST be implemented as a streaming
  parser (e.g., element-at-a-time iteration that releases parsed
  elements as it advances), per Constitution Principle II. Validation
  of bounded memory at full-dump scale is deferred to the Fase 3 spec;
  this spec requires the *architecture*, not a scale benchmark.
- **FR-006**: The pipeline MUST write Parquet outputs in batches; no
  step may accumulate the entire dataset into a single in-process
  collection before writing.

#### Staging contracts

- **FR-007**: The staging step MUST emit Parquet outputs with the
  columns and grain documented in source spec §6.1–6.8:
  `stg_releases`, `stg_release_artists`, `stg_release_labels`,
  `stg_release_formats`, `stg_release_format_descriptions`,
  `stg_release_genres`, `stg_release_styles`, `stg_release_tracks`.

#### Clean contracts

- **FR-008**: The clean step MUST emit Parquet outputs with the
  columns documented in source spec §7.1–7.6 and §8.1:
  `clean_releases`, `clean_release_artists`, `clean_release_labels`,
  `clean_release_formats`, `clean_release_genres`,
  `clean_release_styles`, `release_format_summary`.
- **FR-009**: Date normalization MUST follow source spec §11.1,
  producing `released_date`, `released_date_precision` ∈ {`day`,
  `month`, `year`, `unknown`, `invalid`}, and `decade =
  (year // 10) * 10` when `year` is non-null and within
  `1850 <= year <= current_year + 1`.
- **FR-010**: Format normalization MUST follow source spec §11.2 and
  MUST produce `is_*_format` flags at the release-x-format grain in
  `clean_release_formats`, and `has_*` flags at the release grain in
  `release_format_summary`. Naming conventions are load-bearing per
  Constitution Principle V.

#### Analytics contracts

- **FR-011**: The analytics step MUST emit `release_fact`,
  `release_artist_bridge`, and `release_label_bridge` with the columns
  documented in source spec §9.1–9.3.
- **FR-012**: `release_fact` MUST have grain `release × style`, with
  releases that have zero styles emitting exactly one row with
  `style_order = 0` and `style = NULL`.
- **FR-013**: `release_fact` MUST be built by joining `clean_releases`
  to primary artist, primary label, primary genre,
  `release_format_summary`, and `clean_release_styles`. It MUST NOT
  join directly against `clean_release_formats` (per Constitution
  Principle I and the source spec's explicit prohibition).

#### Publish

- **FR-014**: On a passing run, the publish step MUST produce a
  DuckDB database at `data/published/duckdb/discogs.duckdb`
  containing the tables `release_fact`, `release_artist_bridge`,
  `release_label_bridge`, and the view `release_unique_view` with the
  column set defined in source spec §10.

#### Reproducibility & manifest

- **FR-015**: Every run MUST be assigned a `run_id` (auto-generated if
  not supplied; the auto-generated form MUST be a sortable timestamp).
- **FR-016**: Every run MUST produce a manifest at
  `data/manifests/{run_id}.json` whose minimum content matches the
  template in source spec §13: `run_id`, `snapshot_id`,
  `source_files` (path, size_bytes, checksum each), `outputs`
  (path, row_count each — including
  `release_fact.distinct_release_count`), and `quality_checks`
  (`status` ∈ {`passed`, `passed_with_warnings`, `failed`,
  `incomplete`}, `warnings` array).
- **FR-017**: Every run MUST also produce a log file at
  `data/logs/{run_id}.log`.
- **FR-018**: Re-running the pipeline against the same `snapshot_id`
  with the same configuration and the same input MUST produce
  logically equivalent outputs (row counts, schema, content; ordering
  and filenames may differ if `run_id` differs).

#### Data quality

- **FR-019**: The pipeline MUST execute the data quality checks
  listed in source spec §12.1–12.7 at the appropriate layer
  boundaries.
- **FR-020**: Critical DQ failures MUST cause the run to exit with a
  non-zero status and the manifest's `quality_checks.status` set to
  `failed`. Non-critical issues MUST be appended to
  `quality_checks.warnings` with a status of `passed_with_warnings`
  if no critical failure occurred.
- **FR-021**: The set of checks classified as **critical** is: any
  uniqueness violation on a logical key (e.g., `release_id` in
  `clean_releases`); any value outside an enumerated domain (e.g.,
  `released_date_precision`, `format_group`); more than one
  `is_primary_*` per release; and `COUNT(DISTINCT release_id)` in
  `release_fact` not equal to the row count of `clean_releases`. All
  other documented checks are warnings.
- **FR-022**: On a critical DQ failure, the publish step MUST NOT
  run. The canonical published path
  `data/published/duckdb/discogs.duckdb` MUST be left untouched (the
  previous successful publish, if any, remains). Published DuckDB
  artifacts MUST always reflect a passing run. *(Resolution of
  Question 3, Option A.)*

### Key Entities

- **Snapshot**: A single dated set of Discogs XML dumps, identified
  by `snapshot_id` (e.g., `discogs-2026-04`). Lives under
  `data/raw/discogs/{snapshot_id}/`. Treated as immutable input.
- **Run**: A single execution of the pipeline against a snapshot,
  identified by `run_id`. Owns its own staging, clean, and analytics
  output directories, manifest, and log. Multiple runs over the same
  snapshot are allowed and independent.
- **Release** *(domain entity)*: A Discogs release. Identified by
  `release_id`. The atomic unit of the analytical surface.
- **Style / Genre / Format / Artist / Label** *(domain entities)*:
  Attributes of a release exposed in their own clean tables and
  bridges, with grain and contracts as documented in the source spec.
- **Manifest**: The JSON record of a run — inputs, outputs, status,
  warnings. The audit trail required by Constitution Principle III.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a successful run on the curated sample, every
  table required by source spec §20 (Functional acceptance)
  exists on disk and is queryable in DuckDB. Coverage: 100% of the
  listed tables and the view.
- **SC-002**: Re-running the pipeline against the same curated
  sample with no code changes produces a `release_fact` whose
  total row count and distinct-release count match the prior run
  exactly. Tolerance: 0 difference.
- **SC-003**: After a successful run, the agent's canonical
  example query (US1 acceptance scenario 4) executes against the
  published DuckDB without further data preparation and returns a
  row set whose decades correspond to Techno-styled releases in the
  sample.
- **SC-004**: Time-to-first-DuckDB on a sample of ≤ 1000 releases
  (using `--limit-releases 1000` if the sample is larger) is under
  60 seconds on a developer laptop, supporting the constitution's
  "sample-first iteration" norm.
- **SC-005**: A re-run with `--skip-existing` on a complete
  previous run skips at least one already-complete step (verifiable
  in the run log) without re-executing it.
- **SC-006**: On a sample crafted to trigger one critical DQ
  failure (e.g., a duplicated `release_id`), the run exits with a
  non-zero status, the manifest records
  `quality_checks.status = "failed"`, and
  `data/published/duckdb/discogs.duckdb` is byte-identical to its
  state before the failed run (or absent if no prior publish
  existed). *(Validates FR-022.)*

## Assumptions

- **Component scope**: This spec covers the `etl/` component only.
  The analytics agent (`agent/`) is a separate, future spec
  (Constitution Principle VI).
- **Phase scope**: This spec is **Fase 1 only** (sample vertical
  slice). Fase 2 (real-world XML variability), Fase 3 (full-dump
  scale on laptop), Fase 4 (masters/artists), and Fase 5
  (downloader) are deferred to follow-up specs.
  *(Resolution of Question 1, Option B.)*
- **Masters/artists**: Strictly deferred. This spec parses
  `releases.xml` only; `masters.xml` and `artists.xml` are not
  read or referenced. `stg_masters` and `stg_artists` are NOT
  produced by this spec.
  *(Resolution of Question 2, Option A.)*
- **Sample data**: A curated releases XML sample (a few hundred to
  a few thousand `<release>` elements) is available at the
  configured raw path during development and testing. Acquisition
  and curation of the sample is outside this spec.
- **Data layout**: Raw inputs at
  `data/raw/discogs/{snapshot_id}/releases.xml`; staging / clean /
  analytics outputs partitioned by `run_id` under
  `data/{staging,clean,analytics}/{run_id}/`; published DuckDB at
  `data/published/duckdb/discogs.duckdb`; manifest at
  `data/manifests/{run_id}.json`; log at
  `data/logs/{run_id}.log`. Matches source spec and constitution.
- **Output format**: Parquet for intermediate and final tabular
  outputs; DuckDB for the published analytical surface. Fixed by
  constitution.
- **Configuration**: A single `etl/configs/base.yml` (or
  equivalent) carries paths, snapshot id, and limits. No secrets
  are anticipated for the ETL in v1; if needed, they would come
  from a gitignored `.env`.
- **Resumability**: `--skip-existing` operates per-step on whole
  outputs. Per-record incremental parsing (resuming a partially
  written staging Parquet) is NOT a requirement of this spec. A
  failed step is re-run from scratch with `--force`.
- **Testing strategy**: Unit tests over deterministic transforms
  (date normalization, format normalization, primary-* derivation,
  `release_fact` builder) plus a small-sample integration test
  that runs the full pipeline against a fixture XML and asserts on
  the resulting DuckDB. Test fixtures live under `tests/fixtures/`.
  Tests are *recommended*, not gated as acceptance criteria for
  this spec.
- **Discogs licensing**: Use of Discogs XML dumps for offline
  analytics is assumed compatible with Discogs' published data dump
  license; no legal review is part of this feature.

## Clarification History

The questions below were surfaced during initial drafting and
resolved before this spec left Draft.

| Question | Topic | Selected option |
|----------|-------|-----------------|
| Q1 | Phase scope of this single spec | **B** — Fase 1 only (US1). Fases 2 and 3 are follow-up specs. |
| Q2 | Masters / artists XML handling | **A** — Strictly deferred. Releases-only. |
| Q3 | Behavior on critical data-quality failure | **A** — Publish never runs on a failed run; previous publish untouched. |

These resolutions are encoded into the spec body (FR-022 for Q3;
Assumptions section for Q1 and Q2) and into the scope statement at
the top of this document.
