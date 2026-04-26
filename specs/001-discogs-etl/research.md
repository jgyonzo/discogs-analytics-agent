# Phase 0 Research: Discogs ETL — Fase 1

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Purpose**: Resolve all technology / approach choices needed before
Phase 1 design. There are no `[NEEDS CLARIFICATION]` markers carried
over from the spec (all three were resolved before plan started); this
document captures *implementation* decisions that the spec
intentionally leaves to the planner.

Each entry: **Decision** — **Rationale** — **Alternatives considered**.

---

## R-01: Streaming XML parser

**Decision**: `lxml.etree.iterparse(path, events=("end",), tag="release")`
with `elem.clear()` plus walk-back to clear ancestor refs after each
parsed `<release>`.

**Rationale**:
- `lxml` is the de-facto streaming XML parser for Python; well-tested,
  C-backed (libxml2), supports streaming over files and over
  `gzip.GzipFile` (relevant for Fase 3 but free here).
- `iterparse` with `tag="release"` plus `clear()` is the canonical
  pattern for Discogs-scale dumps (constant memory regardless of file
  size).
- Satisfies Constitution II (streaming, bounded memory) and FR-005.

**Alternatives considered**:
- Stdlib `xml.etree.ElementTree.iterparse`: slower, no
  `huge_tree` parameter, weaker recovery on malformed elements. Not
  worth the gain in zero-dep purity.
- SAX (`xml.sax`): event-driven, lowest memory, but the imperative
  state machine adds noise for what is essentially a single-element
  iteration. Use only if `lxml.iterparse` shows a real problem at Fase 3
  scale.
- Pure-Python streaming libs (`untangle`, `xmltodict`): build full
  in-memory trees per element, defeat the bounded-memory requirement.

---

## R-02: Parquet writer

**Decision**: `pyarrow.parquet.ParquetWriter` opened per output table
per run, fed by buffered batches of pyarrow `RecordBatch` /
`Table.from_pylist(...)` objects. One `ParquetWriter` instance per
output file; closed in a context manager.

**Rationale**:
- Native row-group batching: each call to `writer.write_table(table)`
  creates one row group. The parser hands the writer fixed-size
  batches (default 50_000 rows) so memory is bounded.
- Schemas can be declared explicitly with `pyarrow.schema(...)`,
  matching source spec §6 / §7 / §9 column types exactly. This
  catches type drift at write time, not at DuckDB load time.
- Dict-of-pylists → `Table.from_pylist(records)` is the simplest
  ergonomic shape for the parser; the writer doesn't need to know
  about pandas.
- Satisfies FR-006 (batched writes).

**Alternatives considered**:
- Pandas `df.to_parquet`: convenient but encourages full-frame
  materialization; we'd have to be disciplined to chunk it manually
  anyway. No real win.
- Polars: faster but adds a non-trivial dependency for a one-shot
  batch write. Not justified for Fase 1.
- Direct `fastparquet`: less tightly integrated with DuckDB's
  Parquet reader; pyarrow is the safer default.

---

## R-03: DuckDB publish strategy

**Decision**: Build the new DuckDB at
`data/published/duckdb/discogs.duckdb.new`, populate it via
`COPY ... FROM 'analytics/{run_id}/*.parquet'`-style loads, create
the `release_unique_view` view, then atomically rename to
`discogs.duckdb`. Only invoked on a passing run (after
`quality_checks` step).

**Rationale**:
- FR-022 requires that on critical DQ failure, the canonical published
  DuckDB stays untouched. Atomic rename is the cleanest way to
  guarantee that even publish-step failures don't leave a half-built
  DB at the canonical path. (Q3=A.)
- DuckDB's `CREATE TABLE ... AS SELECT * FROM read_parquet(...)` is
  fast and avoids any pandas round-trip.
- `os.replace` on POSIX is atomic on the same filesystem — required
  because `data/published/duckdb/` and the temp file live in the same
  directory.
- SC-006 validates this behavior end-to-end.

**Alternatives considered**:
- Write directly to `discogs.duckdb` and roll back on failure: not
  atomic; any crash mid-publish leaves a half-built DB.
- Versioned filenames (`discogs.duckdb.{run_id}` + symlink): adds
  symlink semantics that the agent has to be aware of, and Constitution V
  intentionally pins the canonical path.

---

## R-04: CLI framework

**Decision**: `click` for command and subcommand definition.
`python -m discogs_etl.cli` is the entrypoint; `run` and `step <name>`
are the two top-level subcommands.

**Rationale**:
- `click` has a long stable history, simple decorators for flags, and
  is widely understood in the Python community — low learning cost
  for collaborators on this course project.
- Supports all the flags FR-003 requires: `--config` (Path),
  `--run-id` (str), `--snapshot-id` (str), `--limit-releases` (int),
  `--force` (flag), `--skip-existing` (flag).
- Easy to wire `python -m discogs_etl.cli run` since `__main__.py`
  can `from .cli import cli; cli()`.

**Alternatives considered**:
- `typer`: nicer types-first ergonomics but pulls in `typer`,
  `click`, and `rich` as a triad. Not enough win for Fase 1.
- `argparse`: zero deps but verbose enough that maintaining the flag
  set across two subcommands becomes noisy.

---

## R-05: Configuration

**Decision**: A single YAML file at `etl/configs/base.yml`. Loaded with
`PyYAML` (`yaml.safe_load`). Mapped onto a small `RunConfig` dataclass
in `discogs_etl/pipeline/context.py` for type-safety at use sites.

`base.yml` shape:

```yaml
snapshot_id: discogs-2026-04
paths:
  raw_dir: data/raw/discogs
  staging_dir: data/staging
  clean_dir: data/clean
  analytics_dir: data/analytics
  published_duckdb: data/published/duckdb/discogs.duckdb
  manifests_dir: data/manifests
  logs_dir: data/logs
limits:
  parser_batch_size: 50000
  log_progress_every: 10000
```

CLI flags override config values (`--snapshot-id`, `--limit-releases`).

**Rationale**:
- YAML is what the source spec calls for and matches existing
  course-project conventions. PyYAML is the obvious choice.
- A dataclass (rather than a dict) gives the runner attribute-style
  access (`ctx.config.paths.staging_dir`) and a single place to
  validate.
- Pydantic would be overkill for ~10 config keys with no external
  user input.

**Alternatives considered**:
- TOML: nice but the source spec calls out YAML.
- JSON: not human-friendly enough for hand-edited config.
- Pydantic: adds a heavyweight dep for a tiny config schema.

---

## R-06: Logging

**Decision**: Stdlib `logging` configured at run start to write both
to `data/logs/{run_id}.log` (file handler) and stderr (stream
handler). Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`.
Per-step loggers (`logging.getLogger("discogs_etl.steps.parse_releases")`)
so tracebacks self-describe. Progress messages are emitted via
`logger.info(...)` at the cadence configured in `base.yml`
(`log_progress_every`).

**Rationale**:
- Stdlib `logging` is enough for Fase 1: human-readable text logs
  with timestamps, no JSON ingestion pipeline, no external log sink.
- A single `configure_logging(run_id, config)` call early in
  `init_run` keeps configuration centralized.
- Hooking handlers per-run (not at module import) means re-runs
  don't pollute each other's log files.

**Alternatives considered**:
- `structlog`: structured/JSON logs are useful when a log aggregator
  is consuming them; not the case here.
- `loguru`: nice ergonomics but another dep, and stdlib is fine.

---

## R-07: Manifest persistence

**Decision**: A simple `Manifest` class wrapping a dict; reads
`data/manifests/{run_id}.json` (creating it during `init_run`),
updates fields in memory between steps, writes via `json.dump(...,
indent=2)`. Atomic write: write to `{run_id}.json.tmp`, `os.replace`
to `{run_id}.json`. No schema library — the shape is asserted by
unit test fixtures and matches `contracts/manifest.md`.

**Rationale**:
- The manifest is the source-of-truth audit trail (Constitution III)
  but it's not a public API to anything else; a JSON dict + atomic
  write is sufficient.
- Atomic write prevents partial manifest content if the process is
  killed mid-`finalize_manifest`.
- Keeping the manifest mutation localized in a single module
  (`pipeline/manifest.py`) makes the contract obvious.

**Alternatives considered**:
- Pydantic model for the manifest: would catch shape drift at write
  time, but the same is achievable with a pytest fixture and a
  manual schema document.
- SQLite for runs metadata: overkill; the manifest is per-run and
  one file fits in `data/manifests/`.

---

## R-08: Data quality checks

**Decision**: Hand-rolled checks in `discogs_etl/quality/checks.py`,
each implemented as a small function that takes a pyarrow `Table`
(loaded from the just-written Parquet) and returns a `CheckResult`
with `name`, `severity` (`"critical" | "warning"`), `passed`,
`details`. The `quality_checks` step iterates over the registered
checks for the relevant layer and feeds results into the manifest.
Severity is fixed by FR-021.

**Rationale**:
- The §12 check set is small (≈ 20 assertions across 7 layers).
  Each is a one-liner against a pyarrow Table or a DuckDB query.
- Critical/warning split is normative (FR-021), so encoding it as
  data on each check (rather than via a pluggable framework) keeps
  the policy auditable in one file.
- Avoids dragging in `pandera` / `great_expectations`. The spec
  calls those out as not-needed.

**Alternatives considered**:
- `pandera`: nice schema declaration, but most §12 checks are
  cross-row aggregates (e.g., "at most one is_primary_format = true
  per release") that don't fit pandera's column-schema model
  cleanly.
- `great_expectations`: full-fat data-validation framework — large
  dependency, opinionated config layer, far more than needed here.

---

## R-09: Test approach

**Decision**:
- Unit tests for deterministic transforms only: `date_normalization`,
  `format_normalization`, `text_normalization`, the `release_fact`
  builder (given clean inputs as in-memory pylists), and each
  `quality.checks.*` function (passed in synthetic tables).
- One integration test that runs the full pipeline (`run`
  subcommand) against a tiny committed fixture XML
  (`etl/tests/fixtures/releases_sample.xml`, ~5 releases covering the
  in-scope edge cases) and asserts on:
  - Existence of every expected Parquet file
  - DuckDB tables and the view existing with expected schemas
  - `COUNT(DISTINCT release_id) FROM release_fact` matches input
  - Manifest `quality_checks.status` is `"passed"` or
    `"passed_with_warnings"`
- Tests are *recommended* (per spec Assumptions), not gated by the
  constitution. Tasks list will include them but they are not
  acceptance criteria.

**Rationale**:
- The transforms are pure functions of their inputs — perfect for
  unit testing. Catching a date-parsing bug at unit level is far
  cheaper than reproducing it in an integration run.
- The integration test is the cheapest end-to-end smoke against the
  real CLI / runner / step graph; it validates the wiring that unit
  tests miss.
- Curated fixture (committed under `etl/tests/fixtures/`) covers the
  in-scope edge cases listed in the spec's Edge Cases section so the
  full set of contract behaviors is exercised at least once.

**Alternatives considered**:
- Property-based testing (`hypothesis`): nice for date normalization
  in particular, but Fase 1 budget says simpler is better; revisit in
  Fase 2.
- Snapshot testing of generated Parquet: brittle (column ordering,
  metadata noise) and not necessary if individual transforms are
  unit-tested.

---

## R-10: Atomicity & failure handling

**Decision**:
- Per-step semantics: a step either writes all its declared outputs
  successfully or writes none (use a `.tmp` intermediate then
  `os.replace`). Steps that produce multiple outputs write each
  through the atomic-rename pattern.
- A `--force` re-run with the same `run_id` first removes existing
  step outputs in the affected layer dirs to avoid mixed-state
  artifacts.
- A `--skip-existing` re-run checks each step's declared outputs;
  if all exist, the step is skipped and its previous duration in
  the manifest is preserved.

**Rationale**:
- Matches FR-003's flag semantics and SC-005.
- Atomic per-step writes are a free win against mid-run crashes
  (they're a Fase 2/3 concern primarily, but cheap to do right at
  Fase 1).

**Alternatives considered**:
- Two-phase commit across all steps: way more complexity than
  needed for an offline batch.
- No per-step atomicity, rely on user to clean up: violates the
  spec's expectation that re-runs are deterministic.

---

## Resolved spec clarifications (recap, for traceability)

These were resolved before plan started and are listed here so this
research doc serves as the single design-time reference:

| Question | Answer | Encoded in |
|----------|--------|------------|
| Q1 — Phase scope | **B**: Fase 1 only. | spec.md Scope-at-a-glance + Assumptions; this plan's Summary |
| Q2 — Masters/artists | **A**: Strictly deferred. | spec.md Assumptions; absent files in Project Structure |
| Q3 — Publish on critical DQ failure | **A**: Publish never runs on a failed run; previous publish untouched. | FR-022, SC-006; R-03 above |

## Outcome

All technology choices made, no `[NEEDS CLARIFICATION]` markers
remain, Constitution Check still PASS. Phase 1 (data-model.md,
contracts/, quickstart.md) can proceed.
