# Feature Specification: Discogs ETL — Fase 4 (Masters and Artists)

**Feature Branch**: `003-masters-artists`
**Created**: 2026-04-27
**Status**: Draft (clarifications resolved)
**Component**: `etl/` (per Constitution Principle VI — local laptop runtime)
**Builds on**: `specs/001-discogs-etl/` (Fase 1, merged) and
`specs/002-etl-scaleup/` (Fase 2+3, merged)
**Source**: User description
"I want to continue with the next phases of the etl development called
Fase 4 in the initial spec. We already implemented the first one called
Fase 1 and also Fase 2 + Fase 3, refer to
@docs/discogs_etl_initial_spec.md and the current etl specs and
artifacts in @specs/001-discogs-etl/ and @specs/002-etl-scaleup/."

---

## Scope at a glance

Fase 1 delivered the releases-only sample slice, Fase 2+3 made it
robust on real data and laptop-scale. This spec implements **Fase 4
from `docs/discogs_etl_initial_spec.md` §16**: parsing the
`masters.xml` and `artists.xml` Discogs dumps and surfacing
master-level analytics so the agent can answer questions like "which
works have the most reissues" and (depending on Q1) "what are the
top artists by release count".

**Constitution interaction.** The constitution's `Technical
Constraints / Scope guardrails` block lists `master_fact`,
`artist_dim`, `release_genre_bridge`, `company_bridge` as **explicit
non-goals for v1** but offers an escape hatch: "MUST NOT be smuggled
into v1 features without an amendment to this constitution **or an
explicit scope decision recorded in the relevant feature spec**."
This Fase 4 spec is precisely that "explicit scope decision" — no
constitution amendment is required.

The Fase 1 published-DuckDB stability promise
(`specs/001-discogs-etl/contracts/duckdb-schema.md`) explicitly
contemplates Fase 4: *"MAY add new tables (e.g., `master_fact`,
`artist_dim`). Existing columns / grain on `release_fact` and
bridges remain stable. New columns on existing tables (e.g., a
`master_id` denorm) require a constitution amendment for the
published-surface change."* This spec stays additive — new tables
only; nothing existing changes.

**Resolved scope per Clarification History below (Q1=B, Q3=C):**

- Parse `masters.xml` → `stg_masters` (source spec §6.9).
- Parse `artists.xml` → `stg_artists` (source spec §6.10).
- Normalize to `clean_masters` and `clean_artists` (Parquet only —
  not surfaced in DuckDB this spec; foundation for a future
  `artist_dim` spec).
- Build **`master_fact`** with the rich Q3=C set of derived
  fields: master metadata + `release_count` / `earliest_year` /
  `latest_year` (LEFT JOIN against `clean_releases`) + the
  `primary_genre` and primary `style` derived from the master's
  `main_release` (or NULL when `main_release_id` is missing or
  doesn't resolve).
- Publish `master_fact` to the canonical DuckDB.
- Detect missing `masters.xml` / `artists.xml` per snapshot and
  degrade gracefully (manifest warning, no failure).

**Non-goals for this spec.** `artist_dim` (deferred per Q1=B —
its own future spec; the `clean_artists` parquet produced here
is the foundation, but no DuckDB surface yet).
`release_genre_bridge` (source spec §18.2), `company_bridge`
(§18.4), agent component, AWS execution, Discogs auto-downloader
(Fase 5). Each gets its own future spec.

---

## User Scenarios & Testing *(mandatory)*

The "user" of this ETL is still the developer building the
analytics agent. The single user story below covers master-level
analytics. The artists pipeline (stg + clean only, no DuckDB
surface) is foundational work for a future `artist_dim` spec —
its requirements are captured under Functional Requirements but
no agent-facing user story is delivered for artists in this spec.

### User Story 1 — Master-level analytics from masters.xml (Priority: P1) — MVP increment

The developer can run the pipeline against a snapshot directory
containing `masters.xml` (or `masters.xml.gz`, mirroring Fase 3's
gzip support) and get, in the canonical DuckDB, a queryable
`master_fact` table whose rows answer "which works have the most
reissues", "earliest / latest release year for a master", and
similar work-level questions.

**Why this priority**: Master-level analytics is the highest-impact
Fase 4 addition — Discogs distinguishes between a release (a
specific physical / digital edition) and a master (the underlying
work). Many user-facing questions are master-level, and Fase 1's
`release_fact` cannot answer them without a join target. This
unblocks the agent's "work-level" query patterns.

**Independent Test**:

```bash
# A snapshot dir contains releases.xml + masters.xml + (optionally) artists.xml.
python -m discogs_etl.cli run --config etl/configs/base.yml
# expect exit=0, status passed_with_warnings (truncation as in Fase 2)
duckdb data/published/duckdb/discogs.duckdb -c \
  'SELECT title, release_count FROM master_fact ORDER BY release_count DESC LIMIT 5'
```

**Acceptance Scenarios**:

1. **Given** a snapshot directory containing both `releases.xml` and
   `masters.xml`, **When** the developer runs the full pipeline,
   **Then** the published DuckDB contains a new `master_fact` table
   with one row per distinct master, and `SELECT COUNT(*) FROM
   master_fact` matches the count of fully-formed `<master>`
   elements in the input.
2. **Given** the same input, **When** the developer queries
   `SELECT SUM(release_count) FROM master_fact`, **Then** the
   result equals the count of `clean_releases.master_id` rows that
   are NOT NULL (every release with a master_id contributes
   exactly one to the sum across all masters; consistency check).
3. **Given** a master with `id=42` referenced by 5 releases in
   `clean_releases`, **When** the developer queries
   `SELECT release_count, earliest_year, latest_year FROM
   master_fact WHERE master_id = 42`, **Then** `release_count = 5`
   and `earliest_year` / `latest_year` are the min and max of those
   5 releases' `year` (from `clean_releases.year`, ignoring NULLs).
4. **Given** a master that no release references (orphan master in
   the dump), **When** the developer queries the same row, **Then**
   `release_count = 0` and `earliest_year = NULL` and `latest_year
   = NULL`.
5. **Given** the canonical agent example query "Top 10 works by
   release count", **When** the developer runs
   `SELECT title, release_count FROM master_fact
   ORDER BY release_count DESC LIMIT 10`, **Then** the query
   returns up to 10 rows sorted by `release_count` descending.
6. **Given** a master whose `main_release_id` resolves to a
   release in `clean_releases`, **When** the developer queries
   `SELECT primary_genre, primary_style FROM master_fact
   WHERE master_id = <id>`, **Then** both fields equal the
   `main_release`'s primary genre and primary style as observed
   in `release_fact` (i.e., the values for `style_order = 1` of
   that release_id; `primary_genre` is `release_fact.primary_genre`).
7. **Given** a master whose `main_release_id` is missing or does
   not resolve to any release in `clean_releases`, **When** the
   developer queries the same row, **Then**
   `primary_genre IS NULL` and `primary_style IS NULL`. The row
   itself is still present (no row is dropped for missing
   main_release).
8. **Given** the agent's "top techno works by release count"
   pattern, **When** the developer runs
   `SELECT title, release_count FROM master_fact
   WHERE primary_style = 'Techno'
   ORDER BY release_count DESC LIMIT 10`, **Then** the query
   returns up to 10 master rows whose main_release is
   Techno-styled, sorted by reissue count.

---

### Edge Cases

#### Input availability

- `masters.xml` (or `.gz`) is missing from the snapshot dir →
  pipeline records a `prepare_sources.masters_missing` manifest
  warning and skips parse_masters / normalize_masters /
  build_master_fact / publish-of-master_fact. Run still
  succeeds (passed_with_warnings).
- `artists.xml` (or `.gz`) is missing → analogous behavior with
  `prepare_sources.artists_missing` warning.
- Both missing → run behaves exactly like Fase 2+3 (releases-only).
  Existing release_fact still publishes.
- Truncated `masters.xml` or `artists.xml` mid-element → same
  graceful recovery as Fase 2 truncation handling: stop after the
  last fully-formed `<master>` / `<artist>`, emit a
  `parse_masters.truncated_xml` / `parse_artists.truncated_xml`
  warning, run continues.

#### Data shape

- A `<master>` element with no `<main_release>` → `main_release_id`
  is NULL in the row.
- A `<master>` element whose `<year>` is missing, `0`, or
  unparseable → `year` and `decade` are NULL in `clean_masters` /
  `master_fact`; `released_date_precision` rules from Fase 1's
  date_normalization apply (year-only inputs at most).
- An `<artist>` element with no `<realname>` → `realname` is NULL.
- An artist with very long `<profile>` text → captured in
  `stg_artists` (per source spec §6.10) and propagated to
  `clean_artists` text-normalized; NOT exposed in DuckDB
  (artist_dim deferred per Q1=B).
- A master with `release_count = 0` (no release references it) →
  appears in `master_fact` with `release_count = 0`,
  `earliest_year = NULL`, `latest_year = NULL`,
  `primary_genre = NULL`, `primary_style = NULL`.
- A master whose `main_release_id` doesn't resolve to a row in
  `clean_releases` (because that release was filtered or absent)
  → `primary_genre = NULL`, `primary_style = NULL`. Recorded as a
  `build_master_fact.main_release_unresolved` warning with the
  count; not a failure.
- Duplicate `master_id` or `artist_id` in the input XML → critical
  DQ violation (uniqueness check), treated like FR-022's failure
  path (no publish, manifest reports failed, exit 1, prior DuckDB
  byte-identical).

#### Cross-table consistency

- A `clean_releases.master_id` references a master that does NOT
  appear in `clean_masters` (releases dump out of sync with
  masters dump) → recorded as a manifest warning
  (`build_master_fact.unknown_master_ids` with the count) but does
  NOT fail the run. Such rows still contribute to
  `master_fact.release_count` totals via the LEFT JOIN — the
  spec emits a `master_fact` row for every distinct `master_id`
  seen across `clean_masters` ∪ (`clean_releases.master_id` where
  NOT NULL); orphan-from-releases rows have NULL `title`,
  NULL `main_release_id`, NULL `year`, NULL `decade`,
  NULL `primary_genre`, NULL `primary_style`, but a non-NULL
  `release_count`.
- A `release_artist_bridge.artist_id` references an artist not
  present in `clean_artists` → recorded as a manifest warning
  (`normalize_artists.bridge_unresolved_artists` with the count).
  Does NOT block the run; the `release_artist_bridge` itself is
  not modified.

## Requirements *(mandatory)*

### Functional Requirements

#### Inputs and detection

- **FR-001**: The pipeline MUST auto-detect `masters.xml` /
  `masters.xml.gz` and `artists.xml` / `artists.xml.gz` in the
  snapshot directory using the same suffix-based logic as
  `releases.xml` (FR-010 from spec 002). No new CLI flag is
  introduced.
- **FR-002**: When `masters.xml(.gz)` is missing, the pipeline
  MUST skip the masters-related steps cleanly, emit a
  `prepare_sources.masters_missing` manifest warning, and complete
  the run. Same behavior for `artists.xml(.gz)` /
  `prepare_sources.artists_missing`.

#### Staging contracts

- **FR-003**: The masters-parse step MUST emit `stg_masters`
  Parquet with the columns and grain documented in source spec
  §6.9 (`master_id` (BIGINT, NOT NULL), `title`, `main_release_id`,
  `year_raw`, `run_id`).
- **FR-004**: The artists-parse step MUST emit `stg_artists`
  Parquet with the columns documented in source spec §6.10
  (`artist_id` (BIGINT, NOT NULL), `artist_name`, `realname`,
  `profile`, `run_id`).
- **FR-005**: Both new parsers MUST be streaming (`lxml.iterparse`
  + clear + walk-back, like the releases parser) and MUST handle
  truncated XML via the same `try / except XMLSyntaxError` pattern,
  surfacing `parse_masters.truncated_xml` /
  `parse_artists.truncated_xml` warnings instead of failing.
- **FR-006**: Both parsers MUST accept `.gz` inputs (streaming
  decompression) via the existing `io.input.open_releases_input`
  pattern (or an equivalent generalized opener).

#### Clean contracts

- **FR-007**: `clean_masters` MUST normalize `year_raw` into
  `year` (INTEGER, nullable), `decade` (INTEGER, nullable using
  the same `(year // 10) * 10` rule), and a
  `released_date_precision` -compatible `year_precision` enum
  ∈ {`year`, `unknown`, `invalid`} reflecting whether the year
  was parseable. The Fase 1 date_normalization rules apply
  (year range `[1850, current_year + 1]`).
- **FR-008**: `clean_artists` MUST be a passthrough of
  `stg_artists` with text-normalized `artist_name`, `realname`,
  and `profile` (whitespace strip, empty → NULL). NO additional
  derivations.

#### Analytics contracts

- **FR-009**: `master_fact` MUST be built with one row per
  distinct master that appears in EITHER `clean_masters` OR
  `clean_releases.master_id` (full-outer-join semantic to ensure
  no master_id is dropped). Required columns:
  - `master_id` (BIGINT, NOT NULL) — primary key.
  - `title` (TEXT, nullable) — from `clean_masters`; NULL for
    orphan-from-releases rows.
  - `main_release_id` (BIGINT, nullable) — from `clean_masters`.
  - `year` (INTEGER, nullable), `decade` (INTEGER, nullable) —
    from `clean_masters` (year_raw → year via the same date
    rules as Fase 1; year out of range → NULL with warning).
  - `release_count` (INTEGER, NOT NULL, ≥ 0) — count of
    `clean_releases.master_id = master_id`.
  - `earliest_year` (INTEGER, nullable), `latest_year` (INTEGER,
    nullable) — `MIN`/`MAX` of `clean_releases.year` for releases
    referencing this master (NULL when `release_count = 0` or all
    referencing releases have NULL year).
  - `primary_genre` (TEXT, nullable) — from `release_fact` on the
    main_release: lookup `primary_genre` of the row whose
    `release_id = main_release_id`. NULL when `main_release_id`
    is NULL or doesn't resolve.
  - `primary_style` (TEXT, nullable) — from `release_fact` on the
    main_release: lookup `style` of the row whose
    `release_id = main_release_id` AND `style_order = 1`. NULL
    when not resolvable. *(Note: `release_fact` is row-multiplied
    by style; `style_order = 1` selects the primary style.)*
  - `run_id` (TEXT, NOT NULL).
- **FR-010**: `artist_dim` is **explicitly NOT built in this
  spec** (Q1=B). The artists pipeline produces only `stg_artists`
  (FR-004) and `clean_artists` (FR-008). The DuckDB published
  surface gains `master_fact` only — no `artist_dim` table or
  view. A future spec is expected to build `artist_dim` against
  the `clean_artists` foundation produced here.

#### Publish

- **FR-011**: On a passing run, the publish step MUST add
  `master_fact` to the canonical DuckDB alongside the existing
  Fase 1 tables. **Existing tables and the `release_unique_view`
  view MUST remain unchanged** (FR-021 from spec 002 is binding
  here too).
- **FR-012**: When the publish step runs but the masters steps
  were skipped (input missing), `master_fact` MUST NOT appear in
  the published DuckDB (do NOT publish an empty shell); the
  manifest's `outputs.published.duckdb.tables` list reflects what
  was actually published.

#### Reproducibility & manifest

- **FR-013**: New step entries MUST appear in
  `manifest.step_durations` and `manifest.step_metrics` for every
  Fase 4 step that runs: `parse_masters`, `parse_artists`,
  `normalize_masters`, `normalize_artists`, `build_master_fact`.
- **FR-014**: New manifest output entries under
  `outputs.staging.{stg_masters, stg_artists}`,
  `outputs.clean.{clean_masters, clean_artists}`, and
  `outputs.analytics.master_fact` (the last only when masters
  steps ran).

#### Data quality

- **FR-015**: Critical DQ checks for the new layers:
  - `stg_masters.master_id_not_null` / `master_id_unique`
  - `stg_artists.artist_id_not_null` / `artist_id_unique`
  - `clean_masters.master_id_unique`
  - `clean_artists.artist_id_unique`
  - `master_fact.master_id_unique`
  - `master_fact.release_count_non_negative` (warning severity
    per FR-021 from spec 001)
  - `master_fact.sum_release_count_equals_clean_releases_with_master_id`
    (a critical cross-table consistency check, validated via
    SC-003)
- **FR-016**: All DQ checks for new layers MUST be implementable
  in both in-memory and DuckDB-SQL flavors via the
  `quality.dispatch` pattern from spec 002 (FR-014 of spec 002).
  The same parity guarantee applies — the new SQL siblings MUST
  return identical `(name, layer, table, severity, passed)` to
  their in-memory counterparts.

#### Cross-cutting

- **FR-017**: The CLI surface MUST NOT change in a
  backwards-incompatible way. No new flags (per FR-001's
  auto-detect approach). Existing scripts continue to work.
- **FR-018**: The published DuckDB schema for *existing* tables
  (`release_fact`, `release_artist_bridge`, `release_label_bridge`,
  `release_unique_view`) MUST NOT change. Adding `master_fact` and
  `artist_dim` is permitted by the Fase 1 contract's stability
  promise; modifying existing columns / adding `master_id` denorm
  to `release_fact` is NOT permitted by this spec and would
  require a constitution amendment.
- **FR-019**: All 70 tests from spec 002 (Fase 1 + Fase 2+3) MUST
  continue to pass unchanged. New tests are additive only.

### Key Entities

Inherits from Fase 1+2+3. New entities introduced here:

- **Master** — a Discogs *work* (the abstraction above release).
  Identified by `master_id` (BIGINT). One master corresponds to
  zero or more releases (zero is possible for orphan masters).
- **Artist** — Discogs artist record. Identified by `artist_id`
  (BIGINT). Joinable to `release_fact.primary_artist_id` and to
  `release_artist_bridge.artist_id`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

#### US1 — Master analytics

- **SC-001**: Given a snapshot containing `masters.xml`, the run
  publishes `master_fact` to the canonical DuckDB with row count
  = number of distinct master_ids in the union
  (`clean_masters.master_id`) ∪ (`clean_releases.master_id`
  WHERE NOT NULL). No master_id is silently dropped.
- **SC-002**: For any single master that has `N` releases in
  `clean_releases`, `master_fact.release_count = N` and
  `earliest_year` / `latest_year` match `min(year)` / `max(year)`
  over those releases (excluding NULL years).
- **SC-003**: `SELECT SUM(release_count) FROM master_fact` equals
  `SELECT COUNT(*) FROM clean_releases WHERE master_id IS NOT NULL`
  (cross-table consistency check, FR-015).
- **SC-004**: For every master in `master_fact` whose
  `main_release_id` resolves to a row in `release_fact`,
  `primary_genre` and `primary_style` match the
  `release_fact.primary_genre` and the `release_fact.style` value
  at `style_order = 1` for that release_id. For masters whose
  `main_release_id` is NULL or doesn't resolve, both fields are
  NULL.
- **SC-005**: The agent's "top techno works by release count"
  pattern — `SELECT title, release_count FROM master_fact
  WHERE primary_style = 'Techno' ORDER BY release_count DESC
  LIMIT 10` — returns a non-empty result on any snapshot whose
  releases include Techno-styled masters. (Empty result is
  acceptable on tiny curated fixtures lacking Techno masters.)

#### Artists pipeline (foundational only)

- **SC-006**: Given a snapshot containing `artists.xml`, the run
  produces `clean_artists.parquet` whose row count equals the
  count of distinct fully-formed `<artist>` elements in the
  input. The file lives at `data/clean/{run_id}/clean_artists.parquet`.
  It is NOT loaded into DuckDB (per Q1=B; future `artist_dim`
  spec consumes this).
- **SC-007**: `clean_artists.profile` round-trips Unicode
  (e.g., accented characters from realname / profile fields)
  byte-for-byte vs the input.

#### Backward compatibility

- **SC-020**: Running the pipeline on a snapshot WITHOUT
  `masters.xml` or `artists.xml` produces the same release-side
  outputs as in Fase 2+3 (release_fact, bridges, view all
  byte-identical to a Fase 2+3 baseline run, modulo `run_id` and
  timestamps in `parsed_at` / `started_at` / `finished_at`).
  Manifest gains `prepare_sources.masters_missing` and / or
  `prepare_sources.artists_missing` warnings.
- **SC-021**: All 70 tests from spec 002 still pass. New tests
  add to that count; none of the prior assertions are relaxed.

## Assumptions

- **Component scope**: This spec covers the `etl/` component only.
  Constitution Principle VI; same as Fase 1 / 2+3.
- **Constitution path**: This spec uses the constitution's
  "explicit scope decision recorded in the relevant feature spec"
  escape from the v1-only-non-goals language. No constitution
  amendment is required. (A separate housekeeping PATCH amendment
  could later refresh the v1 wording, but is out of scope here.)
- **No existing-table changes**: `release_fact`,
  `release_artist_bridge`, `release_label_bridge`, and
  `release_unique_view` are byte-stable across this spec. Only
  NEW tables are added to the published DuckDB.
- **Fixture availability**: `etl/tests/fixtures/` currently
  contains only releases-side fixtures. This spec assumes the
  user will provide:
  - A small curated `masters_sample.xml` (~5 entries) and
    `artists_sample.xml` (~5 entries) for the integration
    happy-path test, hand-written from the source spec §6.9 / §6.10
    column lists.
  - A small "raw" excerpt of each — e.g.,
    `masters_sample_raw.xml` and `artists_sample_raw.xml` —
    seeded from the same Discogs dump that produced
    `releases_sample_raw.xml` (head -10000 lines of each), to
    exercise truncation handling.
  - Optionally, gitignored larger samples
    (`masters_sample_big_raw.xml` / `artists_sample_big_raw.xml`)
    if scale validation is desired locally. Plan-phase decides
    whether these are tracked, gitignored, or generated.
- **Cross-table reference handling**: A `clean_releases.master_id`
  whose master does not appear in `clean_masters` is treated as a
  warning (`build_master_fact.unknown_master_ids`), not a critical
  failure. `master_fact` includes a row for that id with NULL
  metadata fields and the appropriate `release_count`. A
  `release_artist_bridge.artist_id` not present in `clean_artists`
  is recorded as a warning
  (`normalize_artists.bridge_unresolved_artists`); the bridge
  itself is not modified.
- **No release_fact changes**: A `master_id` denorm column or a
  `master_title` denorm on `release_fact` would require a
  constitution amendment per FR-018 and is explicitly out of scope.
- **Step ordering**: `build_master_fact` runs AFTER
  `build_release_fact` so that the primary_genre / primary_style
  derivation (FR-009) can read `release_fact.parquet` to look up
  the main_release. The runner's existing
  insertion-order-of-steps semantics make this trivial; tasks.md
  pins the order explicitly.
- **No external services**: ETL still runs purely on a developer's
  laptop. No network, no cloud, no auto-download.

## Clarification History

The questions below were surfaced during initial drafting and
resolved before this spec left Draft.

| Question | Topic | Selected option |
|----------|-------|-----------------|
| Q1 | Scope of artist analytics | **B** — Build `master_fact`; **defer `artist_dim` entirely** to a future spec. Staging + clean for both masters AND artists are produced in this spec; only `master_fact` reaches DuckDB. |
| Q2 | `artist_dim` richness | **N/A** — `artist_dim` is not built (Q1=B). The Q2 answer (`minimal`) was recorded as a forward-looking preference for the future `artist_dim` spec, not as part of this spec's deliverable. |
| Q3 | `master_fact` richness | **C** — `master_fact` includes the full set: master metadata + `release_count` / `earliest_year` / `latest_year` (LEFT JOIN against `clean_releases`) + `primary_genre` / `primary_style` (LEFT JOIN against `release_fact` on `main_release_id`, taking the row whose `style_order = 1`). |

These resolutions are encoded in: the Scope-at-a-glance section,
US1 acceptance scenarios 6–8, FR-009 (master_fact column list),
FR-010 (explicit artist_dim deferral), SC-004 / SC-005 (richness
verification), SC-006 / SC-007 (artists pipeline foundation), and
the deferred-non-goals list.
