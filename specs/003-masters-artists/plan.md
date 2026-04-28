# Implementation Plan: Discogs ETL — Fase 4 (Masters and Artists)

**Branch**: `003-masters-artists` | **Date**: 2026-04-27 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-masters-artists/spec.md`
**Components touched**: `etl/` only (per Constitution Principle VI)
**Constitution version**: 1.1.0
**Builds on**: `specs/001-discogs-etl/` and `specs/002-etl-scaleup/` (both merged)

## Summary

Add the masters and artists pipelines on top of the Fase 1+2+3 ETL.
Three additive surfaces:

1. **Two new XML inputs** detected automatically: `masters.xml(.gz)`
   and `artists.xml(.gz)`. Missing inputs degrade gracefully — no
   failure, just a manifest warning per missing file.
2. **Four new Parquet layers**: `stg_masters`, `stg_artists`,
   `clean_masters`, `clean_artists`. The artists side stops at
   clean (per Q1=B); `artist_dim` is a future spec.
3. **One new analytics table** in DuckDB: `master_fact` with the
   Q3=C rich field set — master metadata + join-derived counts +
   `primary_genre` / `primary_style` from the `main_release_id`'s
   row in `release_fact` (style_order = 1).

Existing tables (`release_fact`, `release_artist_bridge`,
`release_label_bridge`, `release_unique_view`) are byte-stable.
The CLI surface gains zero flags. The manifest gains step entries
for the new steps and three new well-known warning names. No
constitution amendment is needed (the spec uses the
"explicit scope decision" escape hatch from
`Technical Constraints / Scope guardrails`).

## Technical Context

**Language/Version**: Python 3.12 (unchanged).

**Primary Dependencies** (delta vs spec 002):
- *(unchanged)* `lxml`, `pyarrow`, `duckdb`, `click`, `PyYAML`,
  `pytest`, plus stdlib `gzip`, `resource`.
- **No new runtime deps** for Fase 4. The new parsers reuse
  `lxml.iterparse`; the gzip-aware opener generalizes to a basename
  parameter; the master_fact build uses DuckDB SQL just like the
  release_fact build.

**Storage**: unchanged layout. Per-run Parquet under
`data/{staging,clean,analytics}/{run_id}/`; canonical published
DuckDB at `data/published/duckdb/discogs.duckdb`.

**Testing**: pytest. New cases:
- Unit: master / artist parser unit tests (truncation handling,
  schema shape, nested-element handling for artists);
  master_fact builder unit test against synthetic clean inputs;
  DQ check parity for the new sum-equals cross-table check.
- Integration:
  - `test_masters_artists_pipeline.py` — full pipeline against
    a curated tiny snapshot (releases + masters + artists XML)
    asserting `master_fact` row count, primary_genre /
    primary_style derivations, and `clean_artists` row count.
  - `test_real_masters_artists_pipeline.py` — against the
    user-provided real raw fixtures
    (`masters_sample_raw.xml` 317 masters, `artists_sample_raw.xml`
    4841 artists) plus the existing `releases_sample_raw.xml` 404
    releases. Asserts truncation handling for both new parsers.
  - **Backward-compat check**: a release-only snapshot must still
    work (drops manifest warnings, no master_fact published) —
    extends an existing test or adds a new one.

**Target Platform**: macOS / Linux developer laptop (unchanged).

**Project Type**: Python CLI library — single component (`etl/`).
No deployment surface changes.

**Performance Goals**:
- Curated tiny snapshot (~10 each of releases / masters / artists):
  total run wall-clock < 5 s.
- Real raw fixtures (404 releases + 317 masters + 4841 artists):
  total wall-clock < 30 s on a laptop. Peak RSS still bounded
  under the 4 GiB cap from spec 002.
- The DQ-check dispatch from spec 002 is reused; default
  threshold (10M) keeps fixture-sized inputs on the in-memory
  path.

**Constraints**:
- Existing release_fact / bridges / view byte-stable (FR-018).
- All 70 prior tests still pass (FR-019).
- `master_fact` and `clean_artists` must NOT appear in the
  published DuckDB or in the per-run analytics dir when their
  inputs are absent (FR-012).
- `build_master_fact` runs AFTER `build_release_fact` so it can
  read `release_fact.parquet` for primary_genre / primary_style
  lookups (Assumptions: Step ordering).
- No CLI breaking changes (FR-017).
- No `release_fact` schema changes (would require constitution
  amendment per FR-018; explicitly out of scope).

**Scale/Scope**: validated empirically against the in-repo small
curated sample (5–10 entries each) and the real raw fixtures
(317 masters, 4841 artists).

## Constitution Check

*Gate: must pass before Phase 0; re-checked at end of Phase 1.*

**Components-touched declaration**: `etl/` only. No `agent/` work;
no imports from a hypothetical `agent/` package.

| # | Principle | Engaged? | How this plan complies |
|---|-----------|----------|------------------------|
| I | Layered, contract-first data architecture | Yes | New layers (`stg_masters`, `stg_artists`, `clean_masters`, `clean_artists`, `master_fact`) get explicit pyarrow schemas in `io/schemas.py`. The `master_fact` build joins via the documented graph (`clean_masters` ∪ `clean_releases.master_id` for the row set, LEFT JOIN to `release_fact` on `main_release_id` for genre/style). No table reaches across non-adjacent layers in violation of the layering. |
| II | Streaming, bounded-memory processing | Yes | New parsers reuse the `lxml.iterparse` + `clear()` + walk-back-siblings pattern (the `MasterStream` / `ArtistStream` classes mirror `ReleaseStream`). Same gzip-aware opener (generalized) means streaming decompression. No code path materializes a full layer. |
| III | Reproducible runs with manifest & logs (NON-NEGOTIABLE) | Yes | Manifest gains entries under `step_durations`, `step_metrics`, `outputs.staging`, `outputs.clean`, `outputs.analytics` for the new steps and tables. Three new well-known warning names: `prepare_sources.masters_missing`, `prepare_sources.artists_missing`, `build_master_fact.unknown_master_ids`, `build_master_fact.main_release_unresolved`, `normalize_artists.bridge_unresolved_artists`. All additive; existing field types unchanged. |
| IV | Data quality gates | Yes | New checks per FR-015 land in `quality/checks.py` with both in-memory and DuckDB-SQL implementations via `quality.dispatch.run_check`. The cross-table sum-equals check is implemented as a standalone helper (always SQL — see R-04) with a parity test. Critical/warning split unchanged. |
| V | Agent-friendly analytics surface | Yes | Existing tables / view unchanged (FR-018). New `master_fact` is documented in the new `contracts/duckdb-schema.md` delta with the same naming-conventions rigor as Fase 1. The DuckDB publisher conditionally adds `master_fact` only when its parquet exists. |
| VI | Two components, one contract | Yes | All edits stay under `etl/`. No new top-level paths. |

**Plan gate verdict**: PASS — no Complexity Tracking entries. The
spec uses the constitution's "explicit scope decision recorded in
the relevant feature spec" escape hatch from the v1-only-non-goals
language; that escape is provided by the constitution itself in
`Technical Constraints / Scope guardrails`. No constitution
amendment is required.

## Project Structure

### Documentation (this feature)

```text
specs/003-masters-artists/
├── spec.md                # Feature spec (committed)
├── plan.md                # This file
├── research.md            # Phase 0 — implementation decisions for Fase 4
├── data-model.md          # Phase 1 — new schemas + master_fact build contract
├── contracts/
│   ├── cli.md             # CLI delta (no changes; backwards compatible)
│   ├── duckdb-schema.md   # DuckDB delta (master_fact added)
│   └── manifest.md        # Manifest delta (new step entries + warnings)
├── quickstart.md          # Phase 1 — developer walkthrough
├── checklists/
│   └── requirements.md    # Spec quality checklist (committed)
└── tasks.md               # Phase 2 output — produced by /speckit-tasks
```

### Source Code (repository root — delta vs spec 002)

Files modified or added (only):

```text
etl/
├── src/discogs_etl/
│   ├── io/
│   │   ├── input.py                            # generalize open_releases_input → open_xml_input(snap_dir, basename)
│   │   └── schemas.py                          # add STG_MASTERS, STG_ARTISTS, CLEAN_MASTERS, CLEAN_ARTISTS, MASTER_FACT
│   ├── parsers/
│   │   ├── masters_parser.py [NEW]             # MasterStream — same iterparse pattern as ReleaseStream
│   │   └── artists_parser.py  [NEW]            # ArtistStream — captures id/name/realname/profile (no nested aliases/members in this spec)
│   ├── transforms/
│   │   └── (unchanged)                         # parse_released's year-only path covers master year_raw
│   ├── steps/
│   │   ├── prepare_sources.py                  # detect masters/artists XML; emit prepare_sources.{masters,artists}_missing warnings
│   │   ├── parse_masters.py     [NEW]          # streaming parse → stg_masters; truncation handling; emit parse_masters.truncated_xml warning
│   │   ├── parse_artists.py     [NEW]          # streaming parse → stg_artists; truncation handling
│   │   ├── normalize_masters.py [NEW]          # stg_masters → clean_masters with year normalization
│   │   ├── normalize_artists.py [NEW]          # stg_artists → clean_artists (text-normalized passthrough)
│   │   └── build_master_fact.py [NEW]          # clean_masters ∪ clean_releases.master_id × release_fact (for primary_*) → master_fact
│   ├── quality/
│   │   └── checks.py                           # add Fase 4 checks (in-memory + SQL siblings) + the cross-table sum-equals helper
│   ├── steps/
│   │   ├── publish_duckdb.py                   # conditionally add master_fact when its parquet exists
│   │   └── quality_checks.py                   # extend layer entrypoints with masters/artists / master_fact checks
│   └── cli.py                                  # extend STEPS list with the new steps in the documented order
└── tests/
    ├── fixtures/
    │   ├── masters_sample.xml      [NEW]       # ~5 curated masters (in-scope edges)
    │   ├── artists_sample.xml      [NEW]       # ~5 curated artists (Unicode realname, long profile, with/without aliases)
    │   ├── masters_sample_bad.xml  [NEW]       # duplicate master_id (FR-022 failure path coverage)
    │   ├── masters_sample_raw.xml  (committed) # 317 real masters, truncated
    │   └── artists_sample_raw.xml  (committed) # 4841 real artists, truncated
    ├── unit/
    │   ├── test_master_parser.py        [NEW]
    │   ├── test_artist_parser.py        [NEW]
    │   ├── test_master_fact_builder.py  [NEW]
    │   └── test_dq_check_parity.py             # extend with new checks
    └── integration/
        ├── test_masters_artists_pipeline.py [NEW]            # full pipeline against curated small fixtures
        ├── test_real_masters_artists_pipeline.py [NEW]       # against the 317-master / 4841-artist real raw fixtures
        └── test_release_only_snapshot.py    [NEW]            # backward-compat: snapshot with only releases.xml
```

**Structure decision**: surgical extension. The Fase 1+2+3 layout
is preserved. New files appear next to their natural neighbors
(parsers/, steps/, fixtures/, tests/unit/, tests/integration/).
Existing files are touched in tightly-scoped places only:
`io/input.py` (generalize the opener), `io/schemas.py` (new
schemas), `steps/prepare_sources.py` (input detection + missing
warnings), `steps/publish_duckdb.py` (conditional master_fact
publish), `steps/quality_checks.py` (new layer entrypoints),
`cli.py` (extend STEPS list).

## Complexity Tracking

> Filled only if Constitution Check has violations that must be
> justified. None for this plan.

*(no entries — all six principles are satisfied without exception)*

## Plan Status

- **Phase 0** — Research: see [research.md](./research.md). All
  implementation decisions documented.
- **Phase 1** — Design & contracts: see
  [data-model.md](./data-model.md), [contracts/](./contracts/),
  and [quickstart.md](./quickstart.md). Constitution Check
  re-evaluated post-design.
- **Phase 2** — Tasks: produced by `/speckit-tasks` (not by this
  command).

## Post-design Constitution Re-check

After producing the Phase 1 artifacts:

- **I (Layered, contract-first)**: `data-model.md` pins every new
  layer's schema (5 new tables) by reference to source spec
  sections. `contracts/duckdb-schema.md` is updated with the
  `master_fact` addition; existing Fase 1 contract remains
  authoritative for the unchanged release tables. ✅
- **II (Streaming, bounded memory)**: `research.md` commits to
  reusing the `ReleaseStream` pattern in
  `MasterStream` / `ArtistStream`; the gzip opener generalization
  preserves streaming decompression; the master_fact build uses
  DuckDB SQL (same scale-friendliness as build_release_fact). ✅
- **III (Reproducible runs)**: `contracts/manifest.md` documents
  the new step entries and warning names; the manifest top-level
  shape stays additive. ✅
- **IV (DQ gates)**: new checks land in `quality/checks.py` with
  both in-memory and SQL paths (parity test extends to cover
  them); cross-table sum-equals helper handled separately. ✅
- **V (Agent-friendly surface)**: existing tables / view stay
  byte-stable; `master_fact` is added with the rich Q3=C field
  set; all naming conventions follow Fase 1's load-bearing
  patterns. ✅
- **VI (Two components, one contract)**: all changes stay under
  `etl/`. ✅

**Final Constitution Check verdict**: PASS — no Complexity
Tracking entries needed.
