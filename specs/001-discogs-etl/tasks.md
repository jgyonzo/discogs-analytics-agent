---

description: "Task list for Discogs ETL — Fase 1 (Sample Vertical Slice)"
---

# Tasks: Discogs ETL — Fase 1 (Sample Vertical Slice)

**Input**: Design documents from `specs/001-discogs-etl/`
**Prerequisites**: `plan.md` (✅), `spec.md` (✅), `research.md` (✅),
`data-model.md` (✅), `contracts/cli.md` (✅),
`contracts/duckdb-schema.md` (✅), `contracts/manifest.md` (✅),
`quickstart.md` (✅).

**Tests**: Recommended (not strictly TDD-gated). The spec
(`spec.md` Assumptions) classifies tests as recommended; the plan
(`research.md` R-09) lists the test set. Test tasks are included
under US1 — they are NOT acceptance gates but are part of the
intended deliverable.

**Organization**: Single user story (US1) — the spec's Q1=B
clarification narrowed scope to Fase 1 only.

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies on
  incomplete tasks).
- **[Story]**: User-story label (e.g., `[US1]`). Required only for
  Phase 3 tasks.

## Path Conventions

- Component code: `etl/src/discogs_etl/...`
- Component tests: `etl/tests/{unit,integration,fixtures}/...`
- Component config: `etl/configs/...`
- Spec docs: `specs/001-discogs-etl/...`
- Runtime data (gitignored): `data/...`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the `etl/` component skeleton, dependency
manifest, base config, gitignore rules, and the curated test
fixtures referenced throughout this spec.

- [X] T001 Create the `etl/` directory tree exactly as specified in
  `plan.md` Project Structure (subfolders only; no Python source
  yet): `etl/configs/`, `etl/src/discogs_etl/{pipeline,steps,parsers,transforms,io,quality}/`,
  `etl/tests/{unit,integration,fixtures}/`. Add empty
  `__init__.py` to every Python package directory under
  `etl/src/discogs_etl/`.
- [X] T002 Create `etl/pyproject.toml` declaring the component as a
  package named `discogs_etl` with dependencies pinned to working
  major versions: `lxml>=5`, `pyarrow>=15`, `duckdb>=1.0`,
  `click>=8.1`, `PyYAML>=6.0`. Test extras under `[project.optional-dependencies].test`:
  `pytest>=8`. Build backend: `setuptools` or `hatchling` (pick one).
  Source layout points at `etl/src/`.
- [X] T003 [P] Create `etl/configs/base.yml` with the schema from
  `research.md` R-05: `snapshot_id`, `paths.{raw_dir,staging_dir,clean_dir,analytics_dir,published_duckdb,manifests_dir,logs_dir}`,
  `limits.{parser_batch_size: 50000, log_progress_every: 10000}`.
  Default `snapshot_id: discogs-2026-04`.
- [X] T004 [P] Update repo-root `.gitignore` to add `data/` so
  pipeline runtime outputs are never committed. Test fixtures
  remain trackable because they live under `etl/tests/fixtures/`,
  not `data/`.
- [X] T005 [P] Create
  `etl/tests/fixtures/releases_sample.xml` — a curated XML
  containing ≈5–10 `<release>` elements wrapped in a single
  `<releases>...</releases>` root, parseable end-to-end by
  `lxml.iterparse`. **Seed**: derive content by cherry-picking from
  `etl/tests/fixtures/releases_sample_raw.xml` (a 404-release real
  Discogs excerpt already provided in this branch). Steps:
  (a) pick 4–6 releases from `releases_sample_raw.xml` that already
  exercise the natural variability — the raw sample contains 106
  releases with `released = "YYYY-MM-00"`, 166 year-only, and 2
  empty/unknown; keep at least one of each;
  (b) hand-edit 3–4 additional releases (or modify picked ones) to
  introduce the edges that do NOT naturally appear in the raw
  sample: one release with no `<styles>` (or `<styles/>`), one with
  no `<formats>`, one with no `<genres>`, one with a
  `<format name="Floppy" qty="1" text=""/>` (or other name unmapped
  per source spec §11.2), and one whose `<labels>` contains two
  `<label>` entries differing only in `catno`. Wrap the result in
  `<releases>...</releases>` and verify with a one-shot
  `lxml.iterparse` smoke that no parse errors occur.
  *Note*: `releases_sample_raw.xml` is intentionally truncated
  mid-release at line 10000 (404 closing tags vs 405 opening) — it
  is a reference / development resource, not a parseable fixture.
  Do not iterate it end-to-end without `recover=True`.
- [X] T006 [P] Create
  `etl/tests/fixtures/releases_sample_bad.xml` — derived from 2–3
  well-formed releases (cherry-picked from `releases_sample_raw.xml`
  or copied from `releases_sample.xml`) wrapped in
  `<releases>...</releases>`, with two of those releases sharing
  the same `id` attribute. Used to exercise FR-022 / SC-006: the
  pipeline must detect this as a critical DQ failure
  (`stg_releases.release_id_unique` violation), the run must exit
  non-zero, and the canonical published DuckDB at
  `data/published/duckdb/discogs.duckdb` must be left
  byte-identical to its prior state (or absent if no prior publish
  existed).

**Checkpoint**: After Phase 1, `pip install -e etl/` succeeds, the
config file loads, and the fixtures parse via `python -c "from lxml
import etree; etree.parse('etl/tests/fixtures/releases_sample.xml')"`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the run-lifecycle plumbing that every step
depends on — context, manifest, generic runner, logging, file
helpers, and the I/O wrappers. No pipeline-specific logic here.

**⚠️ CRITICAL**: User Story 1 implementation cannot begin until this
phase is complete.

- [X] T007 [P] Implement
  `etl/src/discogs_etl/io/file_utils.py`: `make_run_id()` returning
  a sortable timestamp (`YYYY-MM-DDTHH-MM-SS` UTC), `sha256_file(path)`
  for streaming checksum without loading the file, and a small
  `atomic_replace(src, dst)` wrapper around `os.replace` with a
  same-filesystem assertion.
- [X] T008 [P] Implement
  `etl/src/discogs_etl/pipeline/context.py`: a `RunConfig`
  dataclass shaped per `research.md` R-05 (loaded from YAML), a
  `RunContext` dataclass holding `run_id`, `snapshot_id`,
  `RunConfig`, layer paths, and a `logging.Logger`. Include
  `configure_logging(run_id, config)` per `research.md` R-06
  (file handler at `data/logs/{run_id}.log` + stderr stream
  handler with the spec'd format).
- [X] T009 [P] Implement
  `etl/src/discogs_etl/pipeline/manifest.py`: a `Manifest` class
  whose JSON shape matches `contracts/manifest.md` exactly. Methods:
  `Manifest.create(path, run_id, snapshot_id, etl_version, started_at)`,
  `record_step_duration(step_name, seconds)`,
  `record_output(layer, table, path, row_count, **extras)`,
  `record_check_result(result)` (taking a `CheckResult` from
  `quality.checks`), `set_quality_status(status)`,
  `finalize(finished_at)`, `save()` (atomic write).
- [X] T010 [P] Implement
  `etl/src/discogs_etl/io/parquet_writer.py`: a `BatchedParquetWriter`
  context manager wrapping `pyarrow.parquet.ParquetWriter`. Accepts
  an explicit `pyarrow.Schema` (per `data-model.md`'s type-mapping
  notes), buffers rows up to `parser_batch_size`, flushes one row
  group per buffer via `Table.from_pylist(rows, schema=schema)` and
  `writer.write_table(table)`. Closes the writer on `__exit__`.
- [X] T011 Implement
  `etl/src/discogs_etl/io/duckdb_publisher.py`: a `publish(ctx,
  analytics_dir)` function that writes a DuckDB at
  `{paths.published_duckdb}.new`, runs `CREATE TABLE ... AS SELECT
  * FROM read_parquet('{analytics_dir}/release_fact.parquet')` for
  each of the three analytics tables, creates `release_unique_view`
  with the column list from `contracts/duckdb-schema.md` /
  `data-model.md`, closes the connection, and only then calls
  `file_utils.atomic_replace(.new, canonical)`. Depends on T007.
- [X] T012 Implement
  `etl/src/discogs_etl/pipeline/runner.py`: `run_pipeline(ctx,
  steps, *, skip_existing: bool, force: bool)` where `steps` is a
  list of `Step` callables (each a `(ctx) -> StepOutcome`).
  Implements: per-step duration recording, skip-existing semantics
  (if `step.outputs_exist(ctx)`, skip and log), force semantics
  (delete declared step outputs before invoking when `--force`).
  Stops the pipeline on a critical step exception or when
  `quality_checks` reports `failed`. Depends on T008, T009.

**Checkpoint**: Phase 2 complete when these six modules import
successfully (`python -c "import discogs_etl.pipeline.runner"`) and
their unit-level expectations are satisfied (a focused test of the
manifest atomic-write is sufficient evidence; full integration is
Phase 3's job).

---

## Phase 3: User Story 1 — Sample-to-DuckDB vertical slice (Priority: P1) 🎯 MVP

**Goal**: The developer runs a single command against
`etl/tests/fixtures/releases_sample.xml` (or a similarly small
real Discogs sample) and gets a queryable DuckDB at
`data/published/duckdb/discogs.duckdb` containing `release_fact`,
`release_artist_bridge`, `release_label_bridge`, and the
`release_unique_view` view, plus a manifest and log.

**Independent Test** (per `spec.md` US1):

```bash
python -m discogs_etl.cli run --config etl/configs/base.yml
# verify DuckDB exists, manifest reports passed/passed_with_warnings,
# release_unique_view count matches input
```

### Tests for User Story 1 (recommended; not strictly TDD-gated)

> Per `spec.md` Assumptions, tests are *recommended*, not gated.
> List them first so a TDD-inclined developer can red-green-refactor;
> a non-TDD path can land tests alongside or just after the
> implementation tasks they cover.

- [X] T013 [P] [US1] Implement
  `etl/tests/unit/test_date_normalization.py` covering each rule
  in source spec §11.1: `YYYY-MM-DD` → `precision=day`;
  `YYYY-MM-00` → `precision=month`, `day=NULL`,
  `released_date=YYYY-MM-01`; `YYYY` → `precision=year`,
  `released_date=YYYY-01-01`; `0000`/`Unknown`/empty →
  `precision=unknown`; unparseable → `precision=invalid`; year
  outside `[1850, current_year+1]` → `precision=invalid`. Verify
  `decade = (year // 10) * 10` when year is set.
- [X] T014 [P] [US1] Implement
  `etl/tests/unit/test_format_normalization.py` covering the
  source spec §11.2 mapping (each `format_name_raw` →
  `format_group`), and the `is_*_format` derivation rules from
  `format_group` and descriptions (e.g., `LP` / `12"` / `7"`
  descriptions imply `is_vinyl_format`). Include an unmapped value
  test asserting `format_group = "Other"` or `"Unknown"` plus a
  warning side-channel.
- [X] T015 [P] [US1] Implement
  `etl/tests/unit/test_release_fact_builder.py` taking in-memory
  pylist inputs for `clean_releases`, `clean_release_artists`
  (with primary flags), `clean_release_labels` (with primary
  flags), `clean_release_genres` (with primary flags),
  `release_format_summary`, `clean_release_styles`. Asserts
  release-x-style grain (releases with no styles → 1 row,
  `style_order=0`, `style=NULL`); asserts that joining is via the
  enumerated path (no `clean_release_formats`); asserts column set
  matches source spec §9.1.
- [X] T016 [P] [US1] Implement
  `etl/tests/unit/test_quality_checks.py` covering each function
  in `quality/checks.py`. For each check: a `passed=True` case and
  at least one `passed=False` case. Verify severity matches
  `data-model.md`'s critical/warning split (FR-021).
- [X] T017 [P] [US1] Implement
  `etl/tests/integration/test_sample_pipeline.py`:
  - happy path: invoke the `run` CLI subcommand against
    `releases_sample.xml`, assert all expected Parquet outputs
    exist with non-zero `row_count`, assert DuckDB tables and view
    exist, assert
    `COUNT(DISTINCT release_id) FROM release_fact ==
    COUNT(*) FROM release_unique_view ==` input release count
    (modulo dropped rows reported in warnings), assert
    `quality_checks.status ∈ {passed, passed_with_warnings}`,
    assert the canonical agent query (US1 acceptance scenario 4)
    runs.
  - failure path (FR-022 / SC-006): invoke against
    `releases_sample_bad.xml`, capture pre-state byte-hash of
    `data/published/duckdb/discogs.duckdb` if it exists, assert
    exit code != 0, `quality_checks.status == "failed"`,
    `outputs.published.duckdb` absent in manifest, post-state
    byte-hash equals pre-state (or both absent).

### Implementation for User Story 1

#### Transforms, parser, quality library (parallel — no inter-deps)

- [X] T018 [P] [US1] Implement
  `etl/src/discogs_etl/transforms/text_normalization.py`: strip,
  empty-to-null, NFKC normalization (sparingly), and a small
  `clean_text(value: str | None) -> str | None` plus a
  `clean_int(value: str | None) -> int | None` for staging-clean
  conversions.
- [X] T019 [P] [US1] Implement
  `etl/src/discogs_etl/transforms/date_normalization.py` per source
  spec §11.1: `parse_released(raw: str | None) -> ParsedDate`
  returning `(year, month, day, released_date, released_date_precision,
  decade)`. Pure function, no I/O.
- [X] T020 [P] [US1] Implement
  `etl/src/discogs_etl/transforms/format_normalization.py` per
  source spec §11.2: `derive_format_group(name_raw)` →
  `format_group`; `derive_is_vinyl_format(format_group, descriptions)`,
  `derive_is_cd_format(...)`, `derive_is_cassette_format(...)`,
  `derive_is_digital_format(...)`, `derive_is_box_set_format(...)`.
  Pure functions; emit a `FormatNormalizationWarning` for unmapped
  values that the caller can collect.
- [X] T021 [P] [US1] Implement
  `etl/src/discogs_etl/parsers/releases_parser.py`:
  `iter_releases(path) -> Iterator[ReleaseRecord]` using
  `lxml.etree.iterparse(path, events=("end",), tag="release")` per
  `research.md` R-01. Each `ReleaseRecord` is a small dict
  containing the raw text fields needed to populate every staging
  table for that release (releases, artists, labels, formats,
  format_descriptions, genres, styles, tracks). Calls `elem.clear()`
  and ancestor-walk-back after each release. Emits raw text — no
  normalization here.
- [X] T022 [P] [US1] Implement
  `etl/src/discogs_etl/quality/checks.py`: one function per check
  in source spec §12.1–§12.7. Each function takes a `pyarrow.Table`
  (loaded from the just-written Parquet) and returns a `CheckResult`
  dataclass (`name`, `layer`, `table`, `severity`, `passed`,
  `details`). Severity classification per `data-model.md`
  (critical-vs-warning section).
- [X] T023 [P] [US1] Implement
  `etl/src/discogs_etl/quality/report.py`: helpers to aggregate
  `CheckResult` lists into the manifest's
  `quality_checks.{status, warnings, results}` shape per
  `contracts/manifest.md`. `derive_status(results: list[CheckResult])
  -> Literal["passed","passed_with_warnings","failed"]`.

#### Pipeline steps (parallel — different files; runner sequences them at runtime)

- [X] T024 [P] [US1] Implement
  `etl/src/discogs_etl/steps/init_run.py` (Step 0): generate /
  validate `run_id`, ensure all per-run output directories exist,
  create the manifest with `Manifest.create`, configure logging.
- [X] T025 [P] [US1] Implement
  `etl/src/discogs_etl/steps/prepare_sources.py` (Step 1): assert
  `releases.xml` exists at the snapshot path, record `size_bytes`
  and SHA-256 checksum into `manifest.source_files.releases`. No
  copy/move in Fase 1; gzip handling deferred to Fase 3.
- [X] T026 [P] [US1] Implement
  `etl/src/discogs_etl/steps/parse_releases.py` (Step 2): drive
  `parsers.releases_parser.iter_releases(...)` and write all eight
  staging Parquet outputs via `BatchedParquetWriter` per
  `data-model.md`. Honors `--limit-releases` by stopping after N
  records.
- [X] T027 [P] [US1] Implement
  `etl/src/discogs_etl/steps/normalize_releases.py` (Step 5):
  load `stg_releases.parquet`, apply `text_normalization` and
  `date_normalization`, derive per-release counts (`track_count`,
  `artist_count`, `label_count`, `genre_count`, `style_count`,
  `format_count` — counted by joining the staging counts), write
  `clean_releases.parquet` with the schema from source spec §7.1.
- [X] T028 [P] [US1] Implement
  `etl/src/discogs_etl/steps/normalize_release_entities.py`
  (Step 6): produce `clean_release_artists`,
  `clean_release_labels`, `clean_release_formats`,
  `clean_release_genres`, `clean_release_styles` per source spec
  §7.2–§7.6. Apply `text_normalization` to text columns, mark
  `is_primary_*` (= `*_order = 1`), apply the §7.3 dedup rule for
  labels, derive `is_*_format` flags for formats via
  `format_normalization`.
- [X] T029 [P] [US1] Implement
  `etl/src/discogs_etl/steps/build_release_format_summary.py`
  (Step 7): aggregate `clean_release_formats` to release grain;
  derive `primary_format_*` (from `is_primary_format=true`),
  `format_count`, `has_*` flags via `any(is_*_format)`. Output
  `release_format_summary.parquet` per source spec §8.1.
- [X] T030 [P] [US1] Implement
  `etl/src/discogs_etl/steps/build_release_fact.py` (Step 8):
  build `release_fact` per source spec §9.1 using the explicit
  join graph from `data-model.md` (`clean_releases` + primary
  artist/label/genre + `release_format_summary` +
  `clean_release_styles`). Emit one row per `release × style`
  with `style_order = 0`, `style = NULL` for releases with no
  styles. Build `release_artist_bridge` and
  `release_label_bridge` from the corresponding clean tables
  (no analytic logic — just passthrough with primary flags).
  Record
  `outputs.analytics.release_fact.distinct_release_count` in the
  manifest.
- [X] T031 [P] [US1] Implement
  `etl/src/discogs_etl/steps/quality_checks.py` (Step 10):
  iterate over the registered `quality/checks` functions per
  layer, load each Parquet output as a `pyarrow.Table`, run the
  checks, aggregate via `quality/report.derive_status`, and
  feed results into the manifest. Sets the run-level
  quality status; the runner uses this to decide whether to
  proceed to publish.
- [X] T032 [P] [US1] Implement
  `etl/src/discogs_etl/steps/publish_duckdb.py` (Step 9):
  guarded by the runner — only invoked when
  `quality_checks.status ∈ {passed, passed_with_warnings}`.
  Calls `io.duckdb_publisher.publish(ctx, analytics_dir)`.
  Records `outputs.published.duckdb.{path, published_at,
  tables, views}` in the manifest after the atomic rename.
- [X] T033 [P] [US1] Implement
  `etl/src/discogs_etl/steps/finalize_manifest.py` (Step 11):
  set `finished_at`, ensure `step_durations` are populated,
  reconcile `quality_checks.status` (e.g., promote unrecorded
  state to `incomplete`), atomic-write the final manifest.

#### CLI wiring (depends on all steps existing)

- [X] T034 [US1] Implement
  `etl/src/discogs_etl/cli.py` and
  `etl/src/discogs_etl/__main__.py` per `contracts/cli.md`.
  `cli.py`: a `click.Group` with `run` and `step` subcommands,
  flags `--config`, `--run-id`, `--snapshot-id`,
  `--limit-releases`, `--force`, `--skip-existing`. Wires up the
  full step list (T024..T033) into `runner.run_pipeline`.
  Translates exit semantics per `contracts/cli.md` (0 / 1 / 2).
  `__main__.py`: 3-line entrypoint `from .cli import cli; cli()`.

**Checkpoint**: After Phase 3, `python -m discogs_etl.cli run
--config etl/configs/base.yml` against the curated sample fixture
produces a queryable DuckDB and a passing manifest. The integration
test (T017) passes both the happy and failure paths.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Validate the developer-facing surface is accurate,
add component-level documentation, and run end-to-end smoke as a
human would.

- [X] T035 [P] Walk through `specs/001-discogs-etl/quickstart.md`
  by hand on a fresh shell (no prior `data/`), recording any
  step that doesn't behave as documented. File any deviations as
  fixes against the implementation, NOT changes to quickstart.md
  unless the doc itself is wrong.
- [X] T036 [P] Add `etl/README.md` summarizing the component (one
  paragraph), pointing at `specs/001-discogs-etl/` for the
  authoritative design docs and at the repo-root constitution for
  the binding principles. Include the `pip install -e etl/` and
  `python -m discogs_etl.cli --help` quickstart-of-quickstart.
- [X] T037 Run the full unit + integration test suite end-to-end:
  `pytest etl/tests/`. All pass. Record wall-clock to verify
  SC-004 (sample-slice time-to-DuckDB < 60s). Record peak RSS
  (informational, not a Fase 1 gate).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no prerequisites; can start immediately.
- **Phase 2 (Foundational)**: depends on Phase 1. BLOCKS all of
  Phase 3.
- **Phase 3 (User Story 1)**: depends on Phase 2 complete.
- **Phase 4 (Polish)**: depends on Phase 3 complete (specifically
  T034 — the CLI must work end-to-end).

### User Story Dependencies

- Only **US1** in this spec (Q1=B narrowed scope). No cross-story
  dependencies.

### Within User Story 1

Internal task dependencies (beyond the [P] partial order already
encoded above):

- T021 (releases_parser) does NOT depend on T018–T020 (parser
  emits raw text; transforms are applied in clean steps).
- T026 (parse_releases step) depends on T021 (parser) and T010
  (Parquet writer, which is in Phase 2).
- T027 (normalize_releases step) depends on T018, T019.
- T028 (normalize_release_entities step) depends on T018, T020.
- T029 (build_release_format_summary step) has no transform
  deps (it aggregates `clean_release_formats`).
- T030 (build_release_fact step) has no transform deps; depends
  only on the upstream clean Parquet existing at runtime.
- T031 (quality_checks step) depends on T022, T023.
- T032 (publish_duckdb step) depends on T011 (publisher in
  Phase 2).
- T034 (CLI) depends on every step task (T024–T033) and on T012
  (runner, in Phase 2).
- Tests (T013–T017) depend on the corresponding implementation
  files for happy execution but can be drafted in parallel before
  implementation if pursuing TDD; they are NOT blocked by the
  implementation tasks for the *purposes of writing them*.

### Parallel Opportunities

- **Phase 1**: T003, T004, T005, T006 are all [P] with each
  other. T001 must come first; T002 should immediately follow.
- **Phase 2**: T007, T008, T009, T010 are all [P] (different
  files, no inter-deps). Then T011 (deps T007) and T012 (deps
  T008, T009) — T011 and T012 can also be [P] with each other
  (different files, disjoint deps).
- **Phase 3 — tests**: T013–T017 all [P] (different files).
- **Phase 3 — transforms/parser/quality library**: T018–T023 all
  [P] (different files).
- **Phase 3 — steps**: T024–T033 all [P] with each other once
  their transitive deps land (parsers, transforms, quality
  library, Phase 2 modules).
- **Phase 3 — CLI**: T034 is the convergence point; not [P]
  with anything in Phase 3.
- **Phase 4**: T035 and T036 are [P]; T037 must come last.

---

## Parallel Example: User Story 1 transforms + parser + quality library

```bash
# All six files are independent. A single developer can author
# them in any order; multiple developers can work simultaneously.
Task: "Implement transforms/text_normalization.py (T018)"
Task: "Implement transforms/date_normalization.py (T019)"
Task: "Implement transforms/format_normalization.py (T020)"
Task: "Implement parsers/releases_parser.py (T021)"
Task: "Implement quality/checks.py (T022)"
Task: "Implement quality/report.py (T023)"
```

## Parallel Example: User Story 1 step files

```bash
# After T018–T023 land, every step file is implementable in
# parallel — they share no internal imports with each other; the
# runner sequences them at runtime.
Task: "Implement steps/init_run.py (T024)"
Task: "Implement steps/prepare_sources.py (T025)"
Task: "Implement steps/parse_releases.py (T026)"
Task: "Implement steps/normalize_releases.py (T027)"
Task: "Implement steps/normalize_release_entities.py (T028)"
Task: "Implement steps/build_release_format_summary.py (T029)"
Task: "Implement steps/build_release_fact.py (T030)"
Task: "Implement steps/quality_checks.py (T031)"
Task: "Implement steps/publish_duckdb.py (T032)"
Task: "Implement steps/finalize_manifest.py (T033)"
```

---

## Implementation Strategy

### MVP First (User Story 1 — the entire scope of this spec)

1. Complete Phase 1 (Setup): T001–T006.
2. Complete Phase 2 (Foundational): T007–T012.
3. Complete Phase 3 (US1):
   - Optional TDD round: write tests T013–T017 first, watch them
     fail.
   - Implement transforms / parser / quality library: T018–T023.
   - Implement steps: T024–T033.
   - Wire CLI: T034.
   - Make the integration test pass (T017).
4. **STOP and VALIDATE**: run the quickstart by hand; assert
   SC-001..SC-006.
5. Complete Phase 4: T035–T037.

### Incremental Delivery

Phase 1 + Phase 2 + Phase 3 deliver the entire MVP. There are no
later increments inside this spec; subsequent value comes from the
follow-up specs (Fase 2 / Fase 3 / Fase 4 / Fase 5 / agent).

### Parallel Team Strategy

- One developer can complete the whole spec.
- With two developers: split Phase 2 (one takes T007/T008/T009,
  one takes T010/T011/T012), then in Phase 3 split transforms +
  steps along the [P] cuts above.
- More than two developers offers diminishing returns at this
  scope — the integration surface is a single CLI tying ten
  steps together.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete
  tasks.
- `[US1]` label maps every Phase 3 task to the only user story.
  Setup, Foundational, and Polish phases have no story label.
- Tests are recommended, not gated. Skipping all of T013–T017
  does NOT block acceptance per `spec.md`, but is strongly
  discouraged given the contract complexity.
- Verify (the integration test or a manual run) that critical DQ
  failures leave the published DuckDB byte-identical (FR-022 /
  SC-006) before closing the spec out.
- Commit after each task or logical group; the constitution
  doesn't mandate granularity but smaller commits help future
  bisects on data-quality regressions.
- Avoid: vague tasks, same-file conflicts inside a `[P]` set,
  cross-step dependencies that break the runner's ability to
  invoke a single step in isolation.
