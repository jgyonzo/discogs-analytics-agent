# Phase 1 Data Model: Discogs ETL — Fase 1

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Authoritative schema source**: `docs/discogs_etl_initial_spec.md`
sections **6** (staging), **7** (clean), **8** (release_format_summary),
**9** (analytics), **10** (DuckDB), **11** (normalization rules),
**12** (DQ checks), **13** (manifest).

This document does **not** restate every column from the source spec.
It anchors entities to the source-spec sections that define them, adds
the operational entities (Run, Snapshot, Manifest), and pins the
critical-vs-warning DQ classification required by FR-021.

## Run-lifecycle entities

### Snapshot

A dated, immutable set of Discogs XML inputs.

| Field | Type | Origin | Notes |
|---|---|---|---|
| `snapshot_id` | string | config (`base.yml`) or CLI `--snapshot-id` | e.g. `discogs-2026-04`. Used as a directory name. |
| `path` | filesystem path | derived: `{paths.raw_dir}/{snapshot_id}/` | Must contain `releases.xml` |
| `releases_xml` | file | `{path}/releases.xml` | Required for Fase 1 |
| `releases_xml_size_bytes` | integer | `os.stat` | Recorded in manifest |
| `releases_xml_checksum` | string (SHA-256 hex) | computed by `prepare_sources` | Recorded in manifest |

**Lifecycle**: Snapshots are inputs. They are not modified by any
step. Two runs over the same snapshot must yield logically equivalent
outputs (FR-018).

### Run

A single end-to-end execution of the pipeline.

| Field | Type | Origin | Notes |
|---|---|---|---|
| `run_id` | string | auto: `YYYY-MM-DDTHH-MM-SS`, sortable; or CLI `--run-id` | FR-015 |
| `snapshot_id` | string | from Snapshot | recorded in manifest |
| `started_at` | ISO 8601 timestamp | `init_run` | manifest |
| `finished_at` | ISO 8601 timestamp | `finalize_manifest` | manifest |
| `status` | enum: `passed`, `passed_with_warnings`, `failed`, `incomplete` | `quality_checks` + `finalize_manifest` | FR-016, FR-020 |
| `step_durations` | mapping step_name → seconds | runner | manifest |
| `output_paths` | mapping output_name → filesystem path | each step | manifest |
| `warnings` | list of objects | each step + `quality_checks` | manifest |

**Directories owned by a Run**:
- `data/staging/{run_id}/`
- `data/clean/{run_id}/`
- `data/analytics/{run_id}/`
- `data/manifests/{run_id}.json`
- `data/logs/{run_id}.log`

The published DuckDB at `data/published/duckdb/discogs.duckdb` is **not**
owned per-run; the latest passing run's publish replaces it atomically.

### Manifest

Schema documented in [contracts/manifest.md](./contracts/manifest.md);
matches source spec §13 with a small set of additions
(`step_durations`, `started_at`, `finished_at`, `etl_version`). One
JSON file per run.

## Domain entities

### Release

The atomic unit of the analytics surface. Identified by `release_id`
(BIGINT). Every staging, clean, and analytics row that pertains to
releases is keyed (alone or in part) by `release_id`.

### Style / Genre / Format / Artist / Label

Attributes of a release with their own staging, clean, and (where
applicable) bridge tables. Each has its grain documented in source
spec §6 (staging) and §7 (clean). Contracts are inherited unchanged
from the source spec; this plan does not redefine them.

## Layered table contracts

### Staging — `data/staging/{run_id}/*.parquet`

Produced by `parse_releases` (Step 2). Fase 1 emits the full set
listed in source spec §14:

| Table | Source spec § | Grain |
|---|---|---|
| `stg_releases` | 6.1 | 1 row per release |
| `stg_release_artists` | 6.2 | release × main artist |
| `stg_release_labels` | 6.3 | release × label |
| `stg_release_formats` | 6.4 | release × format |
| `stg_release_format_descriptions` | 6.5 | release × format × description |
| `stg_release_genres` | 6.6 | release × genre |
| `stg_release_styles` | 6.7 | release × style |
| `stg_release_tracks` | 6.8 | release × track |

Schemas are exactly the column lists in source spec §6.1–6.8. Type
mapping (XML text → Parquet types):

- `BIGINT` columns: parsed via `int(...)`; non-numeric → `null` plus
  a warning recorded.
- `TEXT` columns: stripped of leading/trailing whitespace; empty
  string → `null` (`text_normalization.py`).
- `BOOLEAN` columns (e.g. `master_is_main_release`): XML "true"/"false"
  literal mapped to bool; missing → `null`.
- `TIMESTAMP` (`parsed_at`): UTC, set by parser at row-emission time.

### Clean — `data/clean/{run_id}/*.parquet`

Produced by `normalize_releases` (Step 5) and
`normalize_release_entities` (Step 6).

| Table | Source spec § | Grain |
|---|---|---|
| `clean_releases` | 7.1 | 1 row per release |
| `clean_release_artists` | 7.2 | release × main artist |
| `clean_release_labels` | 7.3 | release × label (with dedup rule) |
| `clean_release_formats` | 7.4 | release × format (with `is_*_format` flags) |
| `clean_release_genres` | 7.5 | release × genre |
| `clean_release_styles` | 7.6 | release × style |

Plus, produced by `build_release_format_summary` (Step 7):

| Table | Source spec § | Grain |
|---|---|---|
| `release_format_summary` | 8.1 | 1 row per release (with `has_*` flags) |

**Naming-conventions rule (Constitution V):**
- `is_*_format` lives at format grain (`clean_release_formats`).
- `has_*` lives at release grain (`release_format_summary`).
These names are normative and must not be renamed.

**Date normalization** (source spec §11.1) — derives:
`year`, `month`, `day`, `released_date`, `released_date_precision`
(enum: `day` | `month` | `year` | `unknown` | `invalid`), `decade`.

**Format normalization** (source spec §11.2) — `format_name_raw` →
`format_group` ∈ {`Vinyl`, `CD`, `Cassette`, `Digital`, `DVD/Blu-ray`,
`Shellac`, `Box Set`, `Other`, `Unknown`}.

### Analytics — `data/analytics/{run_id}/*.parquet`

Produced by `build_release_fact` (Step 8).

| Table | Source spec § | Grain |
|---|---|---|
| `release_fact` | 9.1 | release × style (releases with no style: 1 row, `style_order=0`, `style=NULL`) |
| `release_artist_bridge` | 9.2 | release × main artist |
| `release_label_bridge` | 9.3 | release × label |

**`release_fact` build contract** (source spec §9.1; FR-013):

```
clean_releases
  LEFT JOIN clean_release_artists  WHERE is_primary_artist
  LEFT JOIN clean_release_labels   WHERE is_primary_label
  LEFT JOIN clean_release_genres   WHERE is_primary_genre
  LEFT JOIN release_format_summary
  LEFT JOIN clean_release_styles
```

Forbidden: any direct join against `clean_release_formats` (use
`release_format_summary`). This is the load-bearing rule that
prevents row multiplication by formats. (Constitution I + V; FR-014.)

### Published — `data/published/duckdb/discogs.duckdb`

Produced by `publish_duckdb` (Step 9), **only on a passing run**
(FR-022). Schema documented in
[contracts/duckdb-schema.md](./contracts/duckdb-schema.md); matches
source spec §10:

- Tables: `release_fact`, `release_artist_bridge`,
  `release_label_bridge`.
- View: `release_unique_view`.

## Data quality classification (FR-021)

The full check set is in source spec §12.1–12.7. Critical-vs-warning
classification (FR-021):

### Critical (run fails, publish skipped, manifest status `failed`)

- `clean_releases.release_id` not unique
- `clean_release_formats`: more than one `is_primary_format = true`
  per `release_id`
- `release_fact`: duplicate `(release_id, style_order)`
- `release_fact`: `COUNT(DISTINCT release_id)` ≠ row count of
  `clean_releases`
- `release_artist_bridge` / `release_label_bridge`: more than one
  `is_primary_*` per release
- Any value outside an enumerated domain:
  - `released_date_precision` not in {`day`, `month`, `year`,
    `unknown`, `invalid`}
  - `format_group` not in the §11.2 enum
- Any null on a non-nullable column per §6/§7/§9 contracts (e.g.,
  `release_id` null in `stg_releases`)

### Warning (recorded in manifest; status `passed_with_warnings` if
no critical failure)

- `track_count` / `artist_count` / `label_count` etc. < 0 (should
  not happen but covered by §12.2)
- `format_name_raw` not present in the §11.2 mapping table → `Other`
  / `Unknown` and a warning lists the unmapped values
- Year out of range `[1850, current_year + 1]` → `released_date_precision
  = "invalid"` and a warning
- Any release row dropped at staging (e.g., missing `release_id`
  in source) → warning with row context

## Manifest content surface (preview)

Authoritative form lives in
[contracts/manifest.md](./contracts/manifest.md). The Run, Snapshot,
and check classifications above flow into it.

## Where this differs from / extends the source spec

- **Operational entities** (Run, Snapshot, Manifest) are formalized
  here because the source spec describes them only at the field
  level under §13. No semantic difference; explicit owners and
  lifecycles only.
- **DQ critical/warning split** is *fixed* here (per FR-021). The
  source spec §12 lists checks but does not classify each one. This
  document's classification IS the contract.
- **All table column lists** are inherited unchanged from the source
  spec sections cited above. No additions or removals in Fase 1.

## Out of scope (per Q1=B, Q2=A)

- `stg_masters`, `stg_artists`, and any `clean_*` / analytics table
  derived from masters or artists XML — Fase 4 spec.
- Anything beyond the curated sample's variability — Fase 2 spec.
- Anything that requires the full Discogs dump to validate — Fase 3
  spec.
