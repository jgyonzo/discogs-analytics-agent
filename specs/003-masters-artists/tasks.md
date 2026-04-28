---

description: "Task list for Discogs ETL — Fase 4 (masters analytics + artists pipeline foundation)"
---

# Tasks: Discogs ETL — Fase 4 (Masters and Artists)

**Input**: Design documents from `specs/003-masters-artists/`
**Prerequisites**: `plan.md` (✅), `spec.md` (✅), `research.md` (✅),
`data-model.md` (✅), `contracts/cli.md` (✅),
`contracts/duckdb-schema.md` (✅), `contracts/manifest.md` (✅),
`quickstart.md` (✅).
**Builds on**: `specs/001-discogs-etl/` (Fase 1) and
`specs/002-etl-scaleup/` (Fase 2+3) — both merged into `main`.

**Tests**: Recommended (not strictly TDD-gated). Per the spec's
testing strategy and the precedent set by Fase 1 / 2+3, test
tasks are included throughout. The cross-table parity guarantee
(FR-016) makes the parity test essentially mandatory.

**Organization**: Single user story (US1 — master-level analytics).
The artists pipeline produces `clean_artists.parquet` only and is
captured under Foundational + the US1 implementation phase
(no DuckDB surface; `artist_dim` is a future spec per Q1=B).

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies
  on incomplete tasks).
- **[Story]**: User-story label (`[US1]`). Required for Phase 3
  tasks; absent for Setup, Foundational, and Polish.

## Path Conventions

- Component code: `etl/src/discogs_etl/...`
- Component tests: `etl/tests/{unit,integration,fixtures}/...`
- Component config: `etl/configs/...`
- Spec docs: `specs/003-masters-artists/...`
- Runtime data (gitignored): `data/...`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Hand-craft the curated small fixtures the integration
tests will assert against. The real raw fixtures
(`masters_sample_raw.xml`, `artists_sample_raw.xml`) are already
committed; this phase builds the small curated siblings whose row
counts and master-id mappings are predictable.

- [X] T001 [P] Create `etl/tests/fixtures/masters_sample.xml` —
  5 hand-crafted `<master>` elements wrapped in `<masters>...</masters>`,
  parseable by `lxml.iterparse`. Master ids and `main_release`
  values designed to align with the existing
  `releases_sample.xml` (Fase 1 fixture) so the integration
  test asserts deterministic master_fact rows. Required entries:
  - `<master id="9001">` with `<main_release>1001</main_release>`,
    `<title>Master Alpha</title>`, `<year>1999</year>`,
    `<data_quality>Correct</data_quality>` (resolves to release
    1001 → `primary_genre=Electronic`, `primary_style=Deep House`).
  - `<master id="9002">` with `<main_release>1002</main_release>`,
    `<title>Master Bravo</title>`, `<year>1998</year>`
    (resolves to release 1002 → `primary_style=Ambient`).
  - `<master id="9003">` with `<main_release>1003</main_release>`,
    `<title>Master Charlie</title>`, `<year>1985</year>`
    (resolves to release 1003 which has NO styles →
    `primary_genre=Rock`, `primary_style=NULL`).
  - `<master id="9998">` with `<main_release>8888</main_release>`
    (NOT a real release_id), `<title>Master Phantom</title>`,
    `<year>2000</year>` — exercises the
    `build_master_fact.main_release_unresolved` warning.
  - `<master id="9999">` with NO `<main_release>` element,
    `<title>Master Lonely</title>`, `<year>1995</year>` —
    orphan-from-masters (no release references it; release_count=0).
  - **Implicit orphan-from-releases**: master ids 9004, 9005,
    9006, 9007 are referenced by `releases_sample.xml` but
    intentionally NOT included here, so master_fact gets 4
    additional rows with NULL metadata and `release_count = 1`.
- [X] T002 [P] Create `etl/tests/fixtures/artists_sample.xml` —
  5 hand-crafted `<artist>` elements wrapped in
  `<artists>...</artists>`, parseable by `lxml.iterparse`.
  Required entries:
  - `<artist><id>10001</id><name>Artist Alpha</name>
    <realname>Real Alpha</realname>
    <profile>Short bio</profile></artist>`.
  - `<artist><id>10002</id><name>Artist Bravo</name></artist>`
    (no realname, no profile).
  - `<artist><id>10003</id><name>Artist Charlie</name>
    <realname>Real Charlie</realname>
    <profile>Multi-paragraph bio with several
    embedded newlines and special punctuation, several
    KB long.</profile></artist>` — exercises long-text round-trip.
  - `<artist><id>10004</id><name>Sigur Rós</name>
    <realname>Iceland Band</realname></artist>` — Unicode in
    `<name>` and `<realname>`.
  - `<artist><id>10005</id><name>Artist Echo</name>
    <aliases><name id="50001">Alias One</name></aliases>
    <members><name id="50002">Member One</name></members>
    <groups><name id="50003">Group One</name></groups>
    </artist>` — verifies the parser tolerates nested
    `<aliases>` / `<members>` / `<groups>` blocks even though
    we don't extract their contents in this spec (Q1=B).
- [X] T003 [P] Create `etl/tests/fixtures/masters_sample_bad.xml`
  — 2 hand-crafted `<master>` elements sharing `id="9001"`
  wrapped in `<masters>...</masters>`. Used to validate FR-022
  failure-path inheritance: critical DQ violation
  (`stg_masters.master_id_unique`) → exit 1, no `master_fact`
  published, prior published DuckDB byte-identical.

**Checkpoint**: Phase 1 complete when each fixture parses cleanly
via `python -c "from lxml import etree;
etree.parse('etl/tests/fixtures/masters_sample.xml')"` (and
similar for the other two), and the existing 70 tests still
pass unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Generalize the gzip-aware input opener, add the new
pyarrow schemas, and extend `prepare_sources` to detect the new
optional XML inputs. These three changes are needed before any
new step can run.

**⚠️ CRITICAL**: User Story 1 implementation cannot begin until
this phase is complete.

- [X] T004 [P] Refactor `etl/src/discogs_etl/io/input.py` per
  `research.md` R-01: rename the existing
  `open_releases_input(snapshot_dir)` to a generalized
  `open_xml_input(snapshot_dir, basename)` that resolves
  `{basename}.xml` vs `{basename}.xml.gz` with the same
  precedence (uncompressed wins, `gz_and_plain_present` flag).
  Keep `open_releases_input(snapshot_dir)` as a thin wrapper
  for backward compatibility (must call `open_xml_input(snapshot_dir,
  "releases")`). Add NEW thin wrappers
  `open_masters_input(snapshot_dir)` and
  `open_artists_input(snapshot_dir)` calling
  `open_xml_input(snapshot_dir, "masters")` and
  `open_xml_input(snapshot_dir, "artists")` respectively. The
  `ReleasesInput` dataclass becomes a generalized `XmlInput` (or
  add an alias); existing callers must continue to work
  unchanged.
- [X] T005 [P] Add five new schemas to
  `etl/src/discogs_etl/io/schemas.py` per
  `data-model.md` "New table contracts":
  - `STG_MASTERS` (source spec §6.9): `master_id` (int64,
    NOT NULL), `title` (string), `main_release_id` (int64),
    `year_raw` (string), `run_id` (string, NOT NULL).
  - `STG_ARTISTS` (source spec §6.10): `artist_id` (int64,
    NOT NULL), `artist_name` (string), `realname` (string),
    `profile` (string), `run_id` (string, NOT NULL).
  - `CLEAN_MASTERS`: `master_id` (int64, NOT NULL),
    `title` (string), `main_release_id` (int64),
    `year` (int32), `decade` (int32),
    `year_precision` (string, NOT NULL — enum
    `year` / `unknown` / `invalid`), `run_id` (string, NOT NULL).
  - `CLEAN_ARTISTS`: same column shape as `STG_ARTISTS` (text
    fields are normalized but the schema mirrors stg).
  - `MASTER_FACT`: `master_id` (int64, NOT NULL),
    `title` (string), `main_release_id` (int64),
    `year` (int32), `decade` (int32),
    `release_count` (int32, NOT NULL),
    `earliest_year` (int32), `latest_year` (int32),
    `primary_genre` (string), `primary_style` (string),
    `run_id` (string, NOT NULL).
- [X] T006 Update `etl/src/discogs_etl/steps/prepare_sources.py`
  per `research.md` R-08: in addition to the existing releases
  resolution, call `open_xml_input(snapshot_dir, "masters")`
  inside a `try / except FileNotFoundError`. On success, record
  size + checksum into `manifest.source_files["masters"]`; on
  exception, emit
  `manifest.warn("prepare_sources.masters_missing", str(snapshot_dir))`.
  Same pattern for artists with the
  `prepare_sources.artists_missing` warning. Releases stays
  required (the existing exception propagates). Depends on T004.

**Checkpoint**: Phase 2 complete when:
- `from discogs_etl.io.input import open_xml_input,
  open_releases_input, open_masters_input, open_artists_input`
  imports cleanly.
- `etl/src/discogs_etl/io/schemas.py` exposes the five new
  schemas.
- A run on a release-only snapshot still passes (Fase 2+3
  baseline) and now records the two new
  `prepare_sources.*_missing` warnings.

---

## Phase 3: User Story 1 — Master-level analytics from masters.xml (Priority: P1) 🎯 MVP

**Goal**: The pipeline auto-detects `masters.xml(.gz)` and
`artists.xml(.gz)`, produces all four new clean-layer parquets +
`master_fact` (with the Q3=C rich field set), and publishes
`master_fact` to the canonical DuckDB. Truncated XML is
gracefully recovered (Fase 2 pattern). Existing release-side
outputs remain byte-stable.

**Independent Test**: see
`specs/003-masters-artists/quickstart.md` §2 (curated small
snapshot with releases + masters + artists fixtures) and §3
(real raw fixtures).

### Tests for User Story 1 (recommended)

- [X] T007 [P] [US1] Add
  `etl/tests/unit/test_master_parser.py` — feed an inline
  `<masters>` fixture (~3 entries) to `MasterStream`, assert
  iteration completes cleanly, the yielded records carry the
  expected fields (`master_id`, `title`, `main_release_id`,
  `year_raw`), Unicode round-trips, and a deliberately
  truncated input populates
  `stream.truncation_info.last_master_id`.
- [X] T008 [P] [US1] Add
  `etl/tests/unit/test_artist_parser.py` — feed an inline
  `<artists>` fixture covering: an artist with full fields
  (id, name, realname, profile), an artist with missing
  realname, an artist with nested `<aliases>` /
  `<members>` / `<groups>` (verify the parser advances past
  them without extracting contents). Assert `truncation_info`
  on a deliberately truncated input.
- [X] T009 [P] [US1] Add
  `etl/tests/unit/test_master_fact_builder.py` — construct
  synthetic `clean_releases.parquet`, `clean_masters.parquet`,
  `release_fact.parquet` in a tmp dir, run
  `BuildMasterFactStep.run(ctx, manifest)`, then assert the
  produced `master_fact.parquet` row count, `release_count` per
  master_id, `earliest_year` / `latest_year`,
  `primary_genre` / `primary_style` derivations
  (resolved + unresolved + style_order=0 corner cases), and the
  `outputs.analytics.master_fact.distinct_master_count` field
  in the manifest.
- [X] T010 [P] [US1] Extend
  `etl/tests/unit/test_dq_check_parity.py` with parity cases
  for the new SQL siblings introduced in T021:
  `_check_unique` already exists for releases; add explicit
  parity coverage for `master_id` / `artist_id` columns
  (different name from `release_id` exercises the SQL
  identifier-quoting path). Add a test for the new standalone
  `_check_sum_release_count_equals` helper (pass + fail
  cases).
- [X] T011 [P] [US1] Add
  `etl/tests/integration/test_masters_artists_pipeline.py` —
  stage a snapshot dir with `releases_sample.xml`,
  `masters_sample.xml`, `artists_sample.xml`. Invoke the `run`
  CLI subcommand. Assertions:
  - exit 0; manifest
    `quality_checks.status == "passed_with_warnings"` (the
    `build_master_fact.unknown_master_ids` warning fires for
    masters 9004-9007; the
    `build_master_fact.main_release_unresolved` warning fires
    for master 9998).
  - DuckDB `SELECT COUNT(*) FROM master_fact` returns 9
    (5 from `clean_masters` + 4 orphan-from-releases).
  - `SELECT SUM(release_count) FROM master_fact` returns 7
    (= `COUNT(*) FROM release_fact WHERE master_id IS NOT
    NULL`-equivalent at this fixture scale; the curated
    fixture has 7 distinct release_ids, all with master_id
    populated).
  - `SELECT primary_genre, primary_style FROM master_fact
    WHERE master_id = 9001` returns
    `('Electronic', 'Deep House')`.
  - `SELECT primary_style FROM master_fact WHERE master_id =
    9003` returns NULL (release 1003 has no styles).
  - `SELECT release_count FROM master_fact WHERE master_id =
    9999` returns 0; `earliest_year` / `latest_year` /
    `primary_genre` / `primary_style` all NULL.
  - `outputs.published.duckdb.tables` includes `master_fact`.
  - `outputs.clean.clean_artists` is present in the manifest
    with row_count = 5.
- [X] T012 [P] [US1] Add
  `etl/tests/integration/test_real_masters_artists_pipeline.py`
  — stage `releases_sample_raw.xml`,
  `masters_sample_raw.xml`, `artists_sample_raw.xml` in a
  snapshot dir. Run the pipeline. Assertions: exit 0; status
  `passed_with_warnings`; warnings include all three
  `parse_*.truncated_xml` names; `master_fact` row count
  approximately matches `317 + (any orphan-from-releases ids)`;
  the cross-table sum-equals consistency holds; UTF-8
  round-trip on artist `realname` (e.g., the `Jesper Dahlbäck`
  entry from artist id=1).
- [X] T013 [P] [US1] Add
  `etl/tests/integration/test_release_only_snapshot.py` —
  stage ONLY `releases_sample.xml` (no masters / artists XML).
  Run the pipeline. Assertions: exit 0; manifest contains
  `prepare_sources.masters_missing` and
  `prepare_sources.artists_missing` warnings; manifest does NOT
  contain `outputs.analytics.master_fact`;
  `outputs.published.duckdb.tables` is exactly
  `["release_fact", "release_artist_bridge",
  "release_label_bridge"]`. DuckDB itself does not contain a
  `master_fact` table (verify via `information_schema`).

### Implementation for User Story 1

#### Parsers (parallel — different files)

- [X] T014 [P] [US1] Add
  `etl/src/discogs_etl/parsers/masters_parser.py` per
  `research.md` R-02. Define
  `class MasterStream(path, *, limit=None)` that mirrors
  `ReleaseStream`: opens its own input via
  `_resolve_input(Path(path))` (the helper from
  `releases_parser.py`, generalized via the parent `io.input`
  module), iterates
  `lxml.etree.iterparse(file_obj, events=("end",), tag="master")`
  with `try / except etree.XMLSyntaxError`, captures
  `truncation_info: TruncationInfo | None`, performs `clear()`
  + walk-back-siblings. The yielded record is a dict with
  fields: `master_id_raw` (the `id` attribute),
  `title` (`<title>` text), `main_release_id_raw`
  (`<main_release>` text), `year_raw` (`<year>` text), and
  `parsed_at` (UTC datetime set once at iteration start).
  Nested `<artists>` / `<genres>` / `<styles>` /
  `<videos>` elements are advanced past but their contents
  are NOT extracted. Provide an `iter_masters(path, *,
  limit=None) -> MasterStream` thin wrapper for symmetry with
  the releases parser.
- [X] T015 [P] [US1] Add
  `etl/src/discogs_etl/parsers/artists_parser.py` per
  `research.md` R-02 / R-07. Define
  `class ArtistStream(path, *, limit=None)` mirroring
  `MasterStream`. Yielded fields:
  `artist_id_raw` (`<id>` text — Discogs artists XML uses
  `<id>` element, not an `id` attribute, so the parser must
  read `_txt(elem.find("id"))`), `artist_name`
  (`<name>` text), `realname` (`<realname>` text),
  `profile` (`<profile>` text), `parsed_at`. Per R-07,
  `<aliases>` / `<members>` / `<groups>` /
  `<urls>` / `<namevariations>` are visited only enough to
  advance lxml's cursor; their contents are NOT extracted in
  this spec. Provide `iter_artists(path, *, limit=None)`
  wrapper.

#### Pipeline steps (parallel — different files; runner sequences them at runtime)

- [X] T016 [P] [US1] Add
  `etl/src/discogs_etl/steps/parse_masters.py` —
  `class ParseMastersStep` mirroring `ParseReleasesStep`.
  `name = "parse_masters"`. Inside `run()`: try
  `open_masters_input(ctx.raw_snapshot_dir)`; on
  `FileNotFoundError`, log "skipping (input missing)" and
  return early (no warning emitted from here — already done in
  prepare_sources). Otherwise, drive a `MasterStream` over the
  snapshot path, write `stg_masters.parquet` via a
  `BatchedParquetWriter` with the `STG_MASTERS` schema (using
  `clean_int` for `master_id_raw` /
  `main_release_id_raw`); drop rows whose `master_id` is
  None with a `parse_masters.dropped_no_master_id` warning;
  emit `parse_masters.truncated_xml` warning when
  `stream.truncation_info` is non-None. Use `ProgressReporter`
  cadence for log lines; record `releases_per_sec` (or rather
  `masters_per_sec` — but use the same `releases_per_sec` key
  to keep the manifest schema additive and consistent).
  Record `outputs.staging.stg_masters.{path,row_count}`.
- [X] T017 [P] [US1] Add
  `etl/src/discogs_etl/steps/parse_artists.py` —
  `class ParseArtistsStep` mirroring T016 but for artists.
  Drives `ArtistStream`. Drops rows with NULL `artist_id`
  with a `parse_artists.dropped_no_artist_id` warning. Emits
  `parse_artists.truncated_xml` warning on truncation.
  Records `outputs.staging.stg_artists.{path,row_count}`.
- [X] T018 [P] [US1] Add
  `etl/src/discogs_etl/steps/normalize_masters.py` —
  `class NormalizeMastersStep`. `name = "normalize_masters"`.
  Inside `run()`: skip if `stg_masters.parquet` doesn't exist
  for this run_id (cascade from T016's missing-input skip).
  Otherwise: read stg_masters, apply `clean_text` to `title`,
  apply `parse_released(year_raw)` from
  `transforms/date_normalization.py` (per `research.md` R-06)
  and map: `year`, `decade` from the result;
  `year_precision` derived as `parsed.released_date_precision
  if it ∈ {year, unknown, invalid} else "invalid"`. Write
  `clean_masters.parquet` via `BatchedParquetWriter` with
  `CLEAN_MASTERS`. Record output. No progress reporter
  needed (small step in practice).
- [X] T019 [P] [US1] Add
  `etl/src/discogs_etl/steps/normalize_artists.py` —
  `class NormalizeArtistsStep`. `name = "normalize_artists"`.
  Skip if `stg_artists.parquet` doesn't exist. Otherwise:
  passthrough with text normalization on `artist_name`,
  `realname`, `profile`. Write `clean_artists.parquet` with
  `CLEAN_ARTISTS` schema. Record output.
  After writing, scan `release_artist_bridge.parquet` (which
  was produced earlier in the run by `build_release_fact`) and
  count artist_ids present in the bridge but absent from the
  newly-written `clean_artists`; if non-zero, emit
  `normalize_artists.bridge_unresolved_artists` warning with
  the count.
- [X] T020 [US1] Add
  `etl/src/discogs_etl/steps/build_master_fact.py` per
  `research.md` R-04. `class BuildMasterFactStep`.
  `name = "build_master_fact"`. Skip if `clean_masters.parquet`
  doesn't exist. Otherwise: open `duckdb.connect(":memory:")`,
  build `master_fact` via the SQL spelled out in `research.md`
  R-04 with the **fix from this tasks file**: split
  primary_genre and primary_style lookups into two LEFT JOINs
  to handle releases with no styles (style_order=0) — use
  `SELECT release_id, ANY_VALUE(primary_genre) AS primary_genre
   FROM release_fact GROUP BY release_id` for `primary_genre`
  (release-grain); use `SELECT release_id, style AS
  primary_style FROM release_fact WHERE style_order = 1` for
  `primary_style` (filter handles row-multiplied grain). Track
  whether the master_universe contains any orphan-from-releases
  ids and emit `build_master_fact.unknown_master_ids` warning
  with the count. Track whether any master's main_release_id
  failed to resolve and emit
  `build_master_fact.main_release_unresolved` warning with
  the count. Write `master_fact.parquet` via
  `BatchedParquetWriter` with `MASTER_FACT` schema. Record
  `outputs.analytics.master_fact.{path,row_count,distinct_master_count}`
  in the manifest. Depends on T005 (`MASTER_FACT` schema).

#### Quality + publish + CLI wiring

- [X] T021 [US1] Update
  `etl/src/discogs_etl/quality/checks.py` per `data-model.md`
  "DQ classification" and `research.md` R-05. Add:
  - **In-memory + SQL siblings** for `_check_no_null` already
    exist; reuse for new layers.
  - **In-memory + SQL siblings** for `_check_unique` (already
    exist; reuse for new layers via `dispatch.run_check`).
  - A NEW standalone helper
    `_check_sum_release_count_equals(master_fact_path,
    clean_releases_path, *, name, layer, table_name)` per
    R-05: SQL-only, opens `duckdb.connect(":memory:")`, runs
    `SELECT (SELECT SUM(release_count) FROM
    read_parquet('...master_fact...')) AS sum_,
    (SELECT COUNT(*) FROM read_parquet('...clean_releases...')
    WHERE master_id IS NOT NULL) AS cnt_`, returns `passed =
    (sum_ == cnt_)`.
  - Extend `run_staging_checks(staging_dir, threshold=...)` to
    add (when `stg_masters.parquet` exists):
    `stg_masters.master_id_not_null` and
    `stg_masters.master_id_unique` (dispatch); same for
    artists when `stg_artists.parquet` exists.
  - Extend `run_clean_checks(clean_dir, threshold=...)` to add:
    `clean_masters.master_id_unique`,
    `clean_masters.year_precision_in_enum` (in_set against
    {`year`, `unknown`, `invalid`}),
    `clean_artists.artist_id_unique`. Each conditional on the
    parquet existing.
  - Extend `run_analytics_checks(analytics_dir,
    clean_releases_row_count, *, threshold)` to add (when
    `master_fact.parquet` exists):
    `master_fact.master_id_unique` (dispatch),
    `master_fact.release_count_non_negative` (warning), and
    the cross-table sum-equals check via the new standalone
    helper.
  Depends on T005 (schemas) and T020 (master_fact existence
  semantics).
- [X] T022 [US1] Update
  `etl/src/discogs_etl/steps/quality_checks.py` to compute the
  `clean_releases_row_count` once and pass through; the layer
  entrypoints from T021 take care of the rest. Verify the
  step still constructs a single `all_results` list and
  invokes `derive_status` with
  `has_freestanding_warnings=...` per Fase 2's logic. Depends
  on T021.
- [X] T023 [US1] Update
  `etl/src/discogs_etl/io/duckdb_publisher.py` per
  `research.md` R-09: split tables into `core_tables`
  (release_fact, release_artist_bridge, release_label_bridge —
  all required) and `optional_tables` (master_fact — added
  only when `master_fact.parquet` exists). Core tables raise
  `FileNotFoundError` if missing (existing behavior); optional
  tables are conditionally created. The `release_unique_view`
  is created on `release_fact` as in Fase 1. The atomic-rename
  pattern is preserved unchanged.
- [X] T024 [US1] Update
  `etl/src/discogs_etl/cli.py`'s `_build_steps()` to extend
  the `STEPS` list with the new steps in the order pinned by
  `contracts/cli.md`:
  - parse_masters (after parse_releases)
  - parse_artists (after parse_masters)
  - normalize_masters (after normalize_release_entities)
  - normalize_artists (after normalize_masters)
  - build_master_fact (after build_release_fact, before
    quality_checks)
  Update `_CLI_TO_INTERNAL` mapping with the new step-name
  aliases (`parse-masters`, `parse-artists`,
  `normalize-masters`, `normalize-artists`,
  `build-master-fact`). Depends on T016–T020.

**Checkpoint**: US1 complete when:
- T011 passes locally
  (`pytest etl/tests/integration/test_masters_artists_pipeline.py
  -v`).
- T012 passes locally
  (`pytest etl/tests/integration/test_real_masters_artists_pipeline.py
  -v`).
- T013 passes locally
  (`pytest etl/tests/integration/test_release_only_snapshot.py
  -v`).
- All 70 prior tests still pass unchanged (FR-019 / SC-021).

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole spec end-to-end and refresh
component docs.

- [X] T025 Run the full test suite from the repo root:
  `pytest etl/tests/`. Expected: all 70 prior tests + the new
  Fase 4 tests (parsers + master_fact builder + DQ parity +
  three integration tests) pass. Record total wall-clock —
  typical target is ~1–2 seconds for the always-on suite.
- [X] T026 [P] Optional: re-run with `DISCOGS_BIG_FIXTURE=1
  pytest etl/tests/integration/test_big_sample_pipeline.py`
  to confirm no scale regression for the Fase 3 path. Should
  still pass in ~7-8 s with peak RSS comfortably under 1 GiB.
- [X] T027 [P] Update `etl/README.md` to mention the Fase 4
  features (auto-detect masters/artists XML, `master_fact`
  table in the published DuckDB with the Q3=C field set,
  artists pipeline foundation for the future `artist_dim`
  spec). Cross-reference
  `specs/003-masters-artists/quickstart.md` for the full
  walkthrough.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no prerequisites; T001 / T002 / T003 are
  all independent and can run in parallel.
- **Phase 2 (Foundational)**: depends on Phase 1. Within Phase
  2: T004 / T005 are [P] with each other; T006 depends on T004.
- **Phase 3 (US1)**: depends on Phase 2 complete. Within US1:
  - Tests (T007–T013) all [P] across separate test files.
    TDD-friendly: write first, watch them fail, then T014+.
  - Parsers (T014, T015) [P] with each other.
  - Step files (T016–T020) [P] across separate files; each
    depends on its parser/transform/io. T020
    (build_master_fact) additionally depends on the existing
    `release_fact` build (no additional task needed; the
    runner's step ordering enforces this at runtime).
  - Quality (T021) and quality_checks step (T022) sequential;
    quality_checks step depends on T021.
  - Publisher (T023) and CLI wiring (T024) — T023 [P] with
    T021/T022; T024 depends on all step files (T016–T020) and
    the runner being unchanged.
- **Phase 4 (Polish)**: depends on US1. T025 is the convergence
  test; T026 is optional (gated by env var); T027 is [P].

### User Story Dependencies

- **US1 (P1)**: depends only on Phase 2 (foundational).
  Independent test = SC-001 + SC-002 + SC-003 + SC-004 +
  SC-005 + SC-006 + SC-007 + SC-020 + SC-021. No other user
  story to coordinate with in this spec (artist_dim is
  deferred per Q1=B).

### Parallel Opportunities

- **Phase 1**: T001 / T002 / T003 [P] with each other (3
  fixture files, no interdependencies).
- **Phase 2**: T004 / T005 [P] with each other; then T006.
- **Phase 3 — tests**: T007 / T008 / T009 / T010 / T011 /
  T012 / T013 all [P] (different test files; gated by Phase 2
  for imports but the test scaffolds themselves are
  independent).
- **Phase 3 — parsers**: T014 / T015 [P] (different files).
- **Phase 3 — step files**: T016 / T017 / T018 / T019 / T020
  all [P] across separate files (the runner sequences them at
  execution time).
- **Phase 3 — terminal**: T023 [P] with T021/T022; T024 is the
  convergence point and not [P].
- **Phase 4**: T026 / T027 [P]; T025 is the gate.

---

## Parallel Example: User Story 1 step files (after parsers + quality lib)

```bash
# After T014–T015 (parsers), T021–T022 (quality library), T023
# (publisher) land, the five new step files can be authored in
# parallel — they share no internal imports with each other.
Task: "Implement steps/parse_masters.py (T016)"
Task: "Implement steps/parse_artists.py (T017)"
Task: "Implement steps/normalize_masters.py (T018)"
Task: "Implement steps/normalize_artists.py (T019)"
Task: "Implement steps/build_master_fact.py (T020)"
```

## Parallel Example: tests across the story

```bash
# After Phase 2 lands, all seven test files can be drafted in
# parallel — TDD-friendly.
Task: "Add tests/unit/test_master_parser.py (T007)"
Task: "Add tests/unit/test_artist_parser.py (T008)"
Task: "Add tests/unit/test_master_fact_builder.py (T009)"
Task: "Extend tests/unit/test_dq_check_parity.py (T010)"
Task: "Add tests/integration/test_masters_artists_pipeline.py (T011)"
Task: "Add tests/integration/test_real_masters_artists_pipeline.py (T012)"
Task: "Add tests/integration/test_release_only_snapshot.py (T013)"
```

---

## Implementation Strategy

### MVP First (User Story 1 — the entire scope of this spec)

1. Phase 1 (Setup, T001–T003): hand-craft the curated fixtures.
2. Phase 2 (Foundational, T004–T006): generalize the input
   opener, add schemas, extend `prepare_sources`.
3. Phase 3 (US1):
   - Optional TDD round: write tests T007–T013 first; watch
     them fail.
   - Implement parsers T014–T015.
   - Implement steps T016–T020.
   - Wire quality T021–T022, publisher T023, CLI T024.
   - Make the integration tests (T011, T012, T013) pass.
4. **STOP and VALIDATE**: SC-001..SC-007, SC-020, SC-021 all
   met locally.
5. Phase 4 (Polish): T025–T027.

### Incremental Delivery

US1 IS the spec. There's no further increment within Fase 4;
the next user value comes from a future spec
(`artist_dim`-as-its-own-spec, or `release_genre_bridge`, or
the agent component).

### Parallel Team Strategy

- One developer can complete the whole spec in a few hours.
- Two developers: split Phase 3 — one takes parsers + masters
  steps + build_master_fact (T014, T016, T018, T020), the
  other takes artists steps + quality + publisher + CLI
  (T015, T017, T019, T021, T022, T023, T024). Tests can be
  written by either or split arbitrarily.
- More than two developers: marginal returns; the integration
  surface is a single CLI tying ~15 steps together.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete
  tasks.
- `[US1]` label maps every Phase 3 task to the only user
  story. Setup, Foundational, and Polish phases carry no
  story label.
- Tests are recommended, not gated. T010 (DQ parity) is
  arguably "near-mandatory" because FR-016 codifies the
  parity guarantee — skipping it leaves a documented contract
  unchecked.
- No published-DuckDB schema changes for *existing* tables
  (FR-018). The new `master_fact` table is permitted by the
  Fase 1 stability promise.
- The constitution's "explicit scope decision recorded in the
  relevant feature spec" path is taken (the spec records it);
  no constitution amendment is needed.
- Commit after each task or logical group; smaller commits
  help bisects on master/artist regressions.
- Avoid: vague tasks, same-file conflicts inside a `[P]` set,
  cross-step dependencies that break the runner's ability to
  invoke a single step in isolation.
