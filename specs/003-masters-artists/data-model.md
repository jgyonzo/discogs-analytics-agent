# Phase 1 Data Model: Discogs ETL — Fase 4

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Authoritative for**: new layers (`stg_masters`, `stg_artists`,
`clean_masters`, `clean_artists`, `master_fact`) and the manifest
extension. Existing Fase 1 / 2+3 contracts continue to govern
everything not diffed here.

The Fase 1 data model
(`specs/001-discogs-etl/data-model.md`) and the Fase 2+3 manifest
extension (`specs/002-etl-scaleup/data-model.md`) remain the
authoritative source for releases-side schemas, the manifest's
top-level shape, and the DQ-dispatch dispatcher. Read this
document together with both.

## What's unchanged

- Run, Snapshot, Release, Manifest entities.
- All releases-side schemas (`stg_releases*`, `clean_releases*`,
  `release_format_summary`, `release_fact`,
  `release_artist_bridge`, `release_label_bridge`) and the
  `release_unique_view` view.
- Critical-vs-warning DQ classification (FR-021 of spec 001).
- Manifest top-level shape, `step_metrics`, the
  `runtime.peak_rss_exceeds_cap` and existing
  `parse_releases.*` warnings.

## What's new in this spec

### Domain entities

- **Master** — Discogs *work* (the abstraction above release).
  Identified by `master_id` (BIGINT). Joinable to
  `release_fact.master_id` and to `release_unique_view.master_id`.
  Zero-or-more releases per master (orphan masters allowed).
- **Artist** — Discogs artist record. Identified by `artist_id`
  (BIGINT). Joinable to `release_fact.primary_artist_id` and to
  `release_artist_bridge.artist_id`. The artists pipeline
  produces `clean_artists` only in this spec; no DuckDB surface
  (Q1=B). A future `artist_dim` spec will consume that foundation.

### New table contracts

#### Staging — `data/staging/{run_id}/`

| Table | Source spec § | Grain | Authoritative columns |
|---|---|---|---|
| `stg_masters` | 6.9 | 1 row per master | `master_id` (BIGINT NOT NULL), `title` (TEXT), `main_release_id` (BIGINT), `year_raw` (TEXT), `run_id` (TEXT NOT NULL) |
| `stg_artists` | 6.10 | 1 row per artist | `artist_id` (BIGINT NOT NULL), `artist_name` (TEXT), `realname` (TEXT), `profile` (TEXT), `run_id` (TEXT NOT NULL) |

Type mapping at parse time mirrors the Fase 1 release path:
`BIGINT` columns parsed via `clean_int(...)` (non-numeric → NULL +
warning); `TEXT` columns stripped of whitespace, empty → NULL
(`text_normalization.clean_text`).

#### Clean — `data/clean/{run_id}/`

| Table | Grain | Columns |
|---|---|---|
| `clean_masters` | 1 row per master | `master_id` (BIGINT NOT NULL), `title` (TEXT, normalized), `main_release_id` (BIGINT), `year` (INTEGER), `decade` (INTEGER), `year_precision` (TEXT NOT NULL, enum: `year` / `unknown` / `invalid`), `run_id` (TEXT NOT NULL) |
| `clean_artists` | 1 row per artist | `artist_id` (BIGINT NOT NULL), `artist_name` (TEXT, normalized), `realname` (TEXT, normalized), `profile` (TEXT, normalized), `run_id` (TEXT NOT NULL) |

`year_precision` valid values:
- `year` — `year_raw` parsed as a 4-digit year in
  `[1850, current_year + 1]`; `year` is populated, `decade =
  (year // 10) * 10`.
- `unknown` — `year_raw` is empty / `Unknown` / `0` / `0000`;
  `year` and `decade` NULL.
- `invalid` — `year_raw` non-empty but unparseable (e.g.,
  out-of-range or non-numeric); `year` and `decade` NULL.

#### Analytics — `data/analytics/{run_id}/`

| Table | Grain | Columns |
|---|---|---|
| `master_fact` | 1 row per master_id in (`clean_masters` ∪ `clean_releases.master_id` WHERE NOT NULL) | `master_id` (BIGINT NOT NULL), `title` (TEXT), `main_release_id` (BIGINT), `year` (INTEGER), `decade` (INTEGER), `release_count` (INTEGER NOT NULL, ≥ 0), `earliest_year` (INTEGER), `latest_year` (INTEGER), `primary_genre` (TEXT), `primary_style` (TEXT), `run_id` (TEXT NOT NULL) |

**`master_fact` build contract** (FR-009; details in
`research.md` R-04):

```
master_universe = DISTINCT (clean_masters ∪ clean_releases WHERE master_id IS NOT NULL)
LEFT JOIN clean_masters ON master_id           → title, main_release_id, year, decade
LEFT JOIN (aggregate of clean_releases by master_id) → release_count, earliest_year, latest_year
LEFT JOIN release_fact (style_order = 1) ON main_release_id → primary_genre, primary_style
```

Required guarantees:
- Every master_id appearing in `clean_masters` OR in
  `clean_releases.master_id` (NOT NULL) has exactly one row in
  `master_fact`.
- `release_count = 0` and `earliest_year = latest_year = NULL` for
  orphan masters (no release references the id).
- `primary_genre = primary_style = NULL` when `main_release_id` is
  NULL or doesn't resolve to a row in `release_fact`.
- `master_id` is unique in `master_fact` (critical DQ check).
- `SUM(release_count) over master_fact = COUNT(*) over
  clean_releases WHERE master_id IS NOT NULL` (critical
  cross-table DQ check).

**`artist_dim` is NOT built in this spec.** Per Q1=B, the artists
pipeline stops at `clean_artists.parquet`. The DuckDB published
surface gains `master_fact` only.

## Data quality classification (FR-015)

All Fase 4 critical checks; warnings as noted.

### Critical (run fails, publish skipped, manifest status `failed`)

- `stg_masters.master_id_not_null` — `null_count == 0`.
- `stg_masters.master_id_unique` — uniqueness on `master_id`
  (in-memory + SQL paths).
- `stg_artists.artist_id_not_null`.
- `stg_artists.artist_id_unique` (in-memory + SQL paths).
- `clean_masters.master_id_unique` (in-memory + SQL paths).
- `clean_masters.year_precision_in_enum` — values ⊂ {`year`,
  `unknown`, `invalid`}.
- `clean_artists.artist_id_unique` (in-memory + SQL paths).
- `master_fact.master_id_unique` (in-memory + SQL paths).
- `master_fact.sum_release_count_equals_clean_releases_with_master_id`
  — standalone SQL helper (`research.md` R-05).

### Warning (recorded; does not fail the run)

- `master_fact.release_count_non_negative` — sanity check.
- (existing) `prepare_sources.masters_missing` — masters input
  absent from snapshot.
- (existing) `prepare_sources.artists_missing` — artists input
  absent.
- (new) `parse_masters.truncated_xml` — masters XML truncated
  mid-element.
- (new) `parse_artists.truncated_xml` — artists XML truncated.
- (new) `build_master_fact.unknown_master_ids` — `clean_releases`
  references master_ids not present in `clean_masters`. Details
  include the count.
- (new) `build_master_fact.main_release_unresolved` — `<master>`'s
  `main_release_id` doesn't resolve to a row in `release_fact`.
- (new) `normalize_artists.bridge_unresolved_artists` —
  `release_artist_bridge.artist_id` references artists not in
  `clean_artists`.

## Manifest extension contract

Authoritative form lives in
[contracts/manifest.md](./contracts/manifest.md). Diff vs
spec 002 in three places:

1. `source_files`: gains optional `masters` and `artists` entries
   (when the corresponding XML is present in the snapshot).
2. `step_durations` and `step_metrics`: gain entries for the new
   conditional steps when they actually run (`parse_masters`,
   `parse_artists`, `normalize_masters`, `normalize_artists`,
   `build_master_fact`).
3. `outputs`: gains optional entries under
   `outputs.staging.{stg_masters, stg_artists}`,
   `outputs.clean.{clean_masters, clean_artists}`, and
   `outputs.analytics.master_fact`.
4. `quality_checks.warnings`: new well-known warning names listed
   above.

All additions are **optional**. A snapshot without `masters.xml`
or `artists.xml` produces a Fase 2+3-shaped manifest with the
two missing-input warnings — no shape break.

## Where this differs from / extends earlier specs

- **Spec 001** (Fase 1): adds new staging / clean / analytics
  tables. Existing tables are byte-stable. Adds the explicit
  step-ordering rule that `build_master_fact` runs after
  `build_release_fact` so it can read `release_fact.parquet` for
  the primary_genre / primary_style lookups.
- **Spec 002** (Fase 2+3): preserves the streaming + bounded-memory
  + truncation-graceful semantics. The DQ-dispatch threshold pattern
  is reused. The manifest extension is purely additive.

## Out of scope

- `artist_dim` (deferred per Q1=B).
- `release_genre_bridge`, `company_bridge`,
  `release_genre_bridge` (source spec §18).
- A `master_id` denorm column on `release_fact` (FR-018: would
  require constitution amendment).
- AWS execution / agent component / Discogs auto-downloader.
