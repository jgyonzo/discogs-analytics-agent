# Implementation Plan: Discogs ETL — Fase 1 (Sample Vertical Slice)

**Branch**: `001-discogs-etl` | **Date**: 2026-04-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-discogs-etl/spec.md`
**Components touched**: `etl/` only (per Constitution Principle VI)
**Constitution version**: 1.1.0

## Summary

Build the smallest end-to-end slice of the Discogs ETL: a Python CLI that
parses a curated `releases.xml` sample in streaming mode, materializes
the layered Parquet contracts (staging → clean → analytics), and
publishes a DuckDB at the canonical path with `release_fact`, the two
bridges, and the `release_unique_view` view. Every run produces a
manifest and a log keyed by `run_id`. Critical data-quality failures
abort the run before publish, leaving any prior published DuckDB
untouched.

Architectural decisions made here (streaming parser via `lxml.iterparse`,
batched Parquet writes via `pyarrow.ParquetWriter`, single CLI
entrypoint via `click`, custom step runner with explicit per-step
contracts) are chosen so that the deferred Fase 2 (real-world XML
variability) and Fase 3 (full-dump scale on a laptop) specs do not have
to redesign anything — they only have to expand validation surface.

## Technical Context

**Language/Version**: Python 3.12 (project venv is 3.12.12; minimum
supported is 3.11 to keep Fase 1 portable across course laptops).

**Primary Dependencies**:
- `lxml` — streaming XML iterparse over `releases.xml`
- `pyarrow` — batched Parquet writes for staging / clean / analytics layers
- `duckdb` — publish step: load Parquet into the canonical DuckDB
- `click` — CLI entrypoint and subcommand routing
- `PyYAML` — read `etl/configs/base.yml`
- `pytest` — unit and integration tests
- *No additional DQ framework* — checks are short and live in
  `discogs_etl.quality.checks`; bringing in `pandera` /
  `great_expectations` would be over-engineering for the v1 surface.

**Storage**:
- Intermediate and final Parquet under `data/{staging,clean,analytics}/{run_id}/`
- Published DuckDB at `data/published/duckdb/discogs.duckdb`
- Manifest at `data/manifests/{run_id}.json`
- Log at `data/logs/{run_id}.log`
- All under repo root; `data/` is gitignored except for fixture
  releases XML committed under `etl/tests/fixtures/`.

**Testing**: pytest. Unit tests over deterministic transforms
(date / format / text normalization, primary-* derivation,
`release_fact` builder). One small-sample integration test that runs
the full pipeline against a committed fixture XML and asserts on the
produced DuckDB.

**Target Platform**: macOS / Linux developer laptop (Constitution
Technical Constraints / ETL). No cloud runtime for ETL in v1. Windows
is not a stated target; if it works incidentally that's fine, but it's
not validated.

**Project Type**: Python CLI library — single component (`etl/`), no
network surface, no UI. Long-running batch process.

**Performance Goals** (Fase 1 only):
- Time-to-first-DuckDB on a sample of ≤ 1000 releases: < 60 s
  (SC-004).
- Streaming-mode parse: peak RSS does not grow with input file size
  beyond a small constant (architecture requirement; benchmark
  deferred to Fase 3).
- A `--skip-existing` re-run must observably skip at least one
  already-complete step (SC-005).

**Constraints**:
- Bounded-memory architecture must be in place even though the
  full-dump benchmark is Fase 3's job (FR-005, Constitution II).
- `data/published/duckdb/discogs.duckdb` is the agent's only data
  surface; on critical DQ failure it MUST be left byte-identical
  (FR-022, SC-006).
- Layer boundaries are tight: `release_fact` MUST NOT join against
  `clean_release_formats` directly (Constitution I, source spec §9.1).
- Naming conventions are load-bearing: `is_*_format` at format grain,
  `has_*` at release grain (Constitution V, FR-010).

**Scale/Scope**: Sample releases XML — a few hundred to a few thousand
`<release>` elements during Fase 1 development and CI. Architecture
must support tens of millions without redesign (validated in Fase 3).

## Constitution Check

*Gate: must pass before Phase 0; re-checked at end of Phase 1.*

**Components-touched declaration**: `etl/` only. No `agent/` code is
written or imported.

| # | Principle | Engaged? | How this plan complies |
|---|-----------|----------|------------------------|
| I | Layered, contract-first data architecture | Yes | Pipeline organized as `raw → staging → clean → analytics → published`. Each step has declared inputs/outputs; `release_fact` consumes `release_format_summary`, never `clean_release_formats` (FR-013). Schema contracts cited by source-spec section in `data-model.md`. |
| II | Streaming, bounded-memory processing | Yes | XML parsed via `lxml.iterparse` with `clear()` on each release element; staging Parquet written by `pyarrow.ParquetWriter` in row-group batches. No code path materializes the full input. (FR-005, FR-006.) |
| III | Reproducible runs with manifest & logs (NON-NEGOTIABLE) | Yes | Every run gets a sortable timestamp `run_id`; `init_run` step creates `data/manifests/{run_id}.json` and `data/logs/{run_id}.log`; CLI flags `--run-id`, `--snapshot-id`, `--limit-releases`, `--force`, `--skip-existing` are all implemented. (FR-003, FR-015..FR-018.) |
| IV | Data quality gates | Yes | Checks per source spec §12 live in `discogs_etl.quality.checks`. Critical vs warning split is fixed by FR-021. Critical failures cause non-zero exit and `quality_checks.status = "failed"` in the manifest (FR-020). |
| V | Agent-friendly analytics surface | Yes | Published surface is exactly `release_fact`, `release_artist_bridge`, `release_label_bridge`, `release_unique_view`. Naming preserved. Publish step is gated on a passing run (FR-022). |
| VI | Two components, one contract | Yes | All code lives under `etl/`. No imports from a future `agent/` package. The boundary surface is the published DuckDB only. |

**Plan gate verdict**: PASS — no violations to record in Complexity
Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-discogs-etl/
├── spec.md                # Feature specification (already committed)
├── plan.md                # This file
├── research.md            # Phase 0 — technology choices and rationales
├── data-model.md          # Phase 1 — entities, table contracts, manifest schema
├── contracts/
│   ├── cli.md             # CLI subcommand and flag contract
│   ├── duckdb-schema.md   # Consumer-facing contract for the published DuckDB
│   └── manifest.md        # Manifest JSON contract
├── quickstart.md          # Phase 1 — developer walkthrough
├── checklists/
│   └── requirements.md    # Spec quality checklist (already committed)
└── tasks.md               # Phase 2 output — produced by /speckit-tasks
```

### Source Code (repository root)

```text
etl/
├── pyproject.toml                              # etl/ component dependency manifest (Constitution VI)
├── configs/
│   └── base.yml                                # Run config: paths, snapshot id, limits, log cadence
├── src/
│   └── discogs_etl/
│       ├── __init__.py
│       ├── cli.py                              # `python -m discogs_etl.cli ...` entrypoint
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── runner.py                       # Orchestrates ordered step execution
│       │   ├── context.py                      # Run context: run_id, paths, config, logger
│       │   └── manifest.py                     # Manifest read/append/finalize
│       ├── steps/
│       │   ├── __init__.py
│       │   ├── init_run.py                     # Step 0
│       │   ├── prepare_sources.py              # Step 1
│       │   ├── parse_releases.py               # Step 2
│       │   ├── normalize_releases.py           # Step 5
│       │   ├── normalize_release_entities.py   # Step 6
│       │   ├── build_release_format_summary.py # Step 7
│       │   ├── build_release_fact.py           # Step 8
│       │   ├── publish_duckdb.py               # Step 9
│       │   ├── quality_checks.py               # Step 10
│       │   └── finalize_manifest.py            # Step 11
│       ├── parsers/
│       │   ├── __init__.py
│       │   └── releases_parser.py              # iterparse over <release>, yield row dicts
│       ├── transforms/
│       │   ├── __init__.py
│       │   ├── date_normalization.py           # source spec §11.1
│       │   ├── format_normalization.py         # source spec §11.2
│       │   └── text_normalization.py           # null/empty/whitespace handling
│       ├── io/
│       │   ├── __init__.py
│       │   ├── parquet_writer.py               # Batched ParquetWriter wrapper
│       │   ├── duckdb_publisher.py             # Atomic publish (write to .new, swap)
│       │   └── file_utils.py                   # checksum, sortable run_id
│       └── quality/
│           ├── __init__.py
│           ├── checks.py                       # source spec §12.1..§12.7
│           └── report.py                       # Aggregate results into manifest format
└── tests/
    ├── fixtures/
    │   └── releases_sample.xml                 # Small committed sample for integration tests
    ├── unit/
    │   ├── test_date_normalization.py
    │   ├── test_format_normalization.py
    │   ├── test_release_fact_builder.py
    │   └── test_quality_checks.py
    └── integration/
        └── test_sample_pipeline.py             # Run full pipeline against fixture; assert on DuckDB

data/                                           # gitignored; runtime only
├── raw/discogs/{snapshot_id}/                  # input releases.xml
├── staging/{run_id}/
├── clean/{run_id}/
├── analytics/{run_id}/
├── published/duckdb/                           # canonical discogs.duckdb
├── manifests/                                  # {run_id}.json
└── logs/                                       # {run_id}.log
```

**Structure decision**: Single-component layout under `etl/` matching
the source spec §14 suggestion, restricted to the steps relevant to
Fase 1 (no `parse_masters.py` / `parse_artists.py` — those land with
the Fase 4 spec). The component owns its own `pyproject.toml` per
Constitution VI; the existing repo-root `.venv/` is reused as the
working environment until the agent component arrives and forces a
revisit. The `data/` tree at repo root is shared runtime state and
remains gitignored except for the explicit `etl/tests/fixtures/`
sample.

## Complexity Tracking

> Filled only if Constitution Check has violations that must be
> justified. None for this plan.

*(no entries — all six principles are satisfied without exception)*

## Plan Status

- **Phase 0** — Research: see [research.md](./research.md). All
  technology choices documented; no NEEDS CLARIFICATION remains.
- **Phase 1** — Design & contracts: see [data-model.md](./data-model.md),
  [contracts/](./contracts/), and [quickstart.md](./quickstart.md).
  Constitution Check re-evaluated post-design (no new violations).
- **Phase 2** — Tasks: produced by `/speckit-tasks` (not by this command).

## Post-design Constitution Re-check

Re-evaluating the six principles against the concrete artifacts
produced in Phase 1:

- **I (Layered, contract-first)**: `data-model.md` and the contracts
  documents pin every layer's schema by reference to source spec
  sections. The `release_fact` builder section explicitly enumerates
  the permitted joins and excludes `clean_release_formats`. ✅
- **II (Streaming, bounded memory)**: `research.md` commits to
  `lxml.iterparse` with `clear()` on each parsed element and
  `pyarrow.ParquetWriter` row-group batching. No code path accumulates
  full datasets. ✅
- **III (Reproducible runs)**: `contracts/cli.md` fixes the flag set;
  `contracts/manifest.md` fixes the manifest content; `quickstart.md`
  walks through producing both. ✅
- **IV (DQ gates)**: `data-model.md` anchors the §12 checks; the
  critical/warning split from FR-021 is encoded in the check
  definitions. ✅
- **V (Agent-friendly surface)**: `contracts/duckdb-schema.md` is the
  *only* artifact a future `agent/` component is allowed to depend on
  from this spec. The view-vs-fact rule is restated there. ✅
- **VI (Two components, one contract)**: nothing under the planned
  layout imports from a hypothetical `agent/`; the boundary remains
  the published DuckDB. ✅

**Final Constitution Check verdict**: PASS — no Complexity Tracking
entries needed.
