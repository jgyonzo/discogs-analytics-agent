# DuckDB Schema Contract: Published Analytics Surface

**Authoritative for**: the only data surface a future `agent/`
component is allowed to depend on from this spec (Constitution
Principle V + VI).

**Path**: `data/published/duckdb/discogs.duckdb`
**Authoritative column-list source**: `docs/discogs_etl_initial_spec.md`
**§ 9** (table contracts) and **§ 10** (DuckDB tables / view).

This document does not restate every column — it pins the surface
visible to agents and the rules they must follow when generating
queries.

## Surface

### Tables

| Name | Grain | Source-spec § |
|---|---|---|
| `release_fact` | release × style | 9.1 |
| `release_artist_bridge` | release × main artist | 9.2 |
| `release_label_bridge` | release × label | 9.3 |

### Views

| Name | Source-spec § | Purpose |
|---|---|---|
| `release_unique_view` | 10 | One row per release. Used for unique counts. |

## Naming conventions (load-bearing)

Per Constitution Principle V, these names MUST be preserved exactly:

- **Format flags at format grain**: `is_vinyl_format`,
  `is_cd_format`, `is_cassette_format`, `is_digital_format`,
  `is_box_set_format`. These live in `clean_release_formats`
  (NOT exposed in DuckDB v1, but listed for future-proofing).
- **Format flags at release grain**: `has_vinyl`, `has_cd`,
  `has_cassette`, `has_digital`, `has_box_set`. These live on
  `release_fact` and `release_unique_view`.
- **Primary attribute keys**: `primary_artist_id`,
  `primary_artist_name`, `primary_label_id`, `primary_label_name`,
  `primary_genre`, `primary_format_raw`, `primary_format_group`.

## Counting rules (NORMATIVE — agent-facing)

- **Unique releases** MUST be counted via either:
  - `SELECT COUNT(DISTINCT release_id) FROM release_fact`
  - `SELECT COUNT(*) FROM release_unique_view`
- `SELECT COUNT(*) FROM release_fact` counts release-style **rows**,
  NOT releases. Use it only when the question is explicitly
  "how many release × style combinations".
- For "how many releases of a given style?", filter `release_fact`
  by `style` and use `COUNT(DISTINCT release_id)`.
- For "how many releases of a given primary genre?", filter
  `release_unique_view` by `primary_genre` and use `COUNT(*)`.

## Joining rules

- `release_fact` is the natural starting point for analyses keyed by
  `style`. Join to `release_artist_bridge` / `release_label_bridge`
  on `release_id` for multi-artist or multi-label analyses.
- The bridges are **not** distinct on `release_id` — a release may
  appear multiple times in `release_artist_bridge` (one row per
  collaborating artist). For "releases per artist" queries this is
  the intended grain.
- For "primary artist per release" lookups, prefer the
  `primary_artist_*` columns on `release_fact` /
  `release_unique_view` (denormalized for query simplicity).

## Stability promise (Fase 1 → Fase 2/3 → Fase 4)

- **Fase 1 (this spec)**: schema as defined here.
- **Fase 2** (real-world XML variability): MAY add warnings/data,
  MUST NOT change column names, types, or grain.
- **Fase 3** (full-dump scale): MUST NOT change schema.
- **Fase 4** (masters / artists): MAY add new tables (e.g.,
  `master_fact`, `artist_dim`). Existing columns / grain on
  `release_fact` and bridges remain stable. New columns on existing
  tables (e.g., a `master_id` denorm) require a constitution
  amendment for the published-surface change.
- Any change that breaks this contract is a MAJOR change per
  Constitution I and requires updating both this document and any
  consumer (the agent component, when it lands).

## Out of scope (Fase 1)

- `master_fact`, `artist_dim`, `release_genre_bridge`,
  `company_bridge` — Fase 4 territory.
- Any indexing, partitioning, or DuckDB-specific physical layout
  guidance — left to the publisher implementation; consumers MUST
  treat the DB as a logical schema only.

## Verification

The tests in `etl/tests/integration/test_sample_pipeline.py` MUST
assert, against the produced DuckDB:

1. The four objects above (3 tables + 1 view) exist.
2. `release_fact` columns match source spec §9.1.
3. `release_unique_view` columns match source spec §10.
4. `COUNT(DISTINCT release_id)` over `release_fact` equals
   `COUNT(*)` over `release_unique_view` equals the number of
   releases in the input sample (modulo documented filter cases —
   e.g., releases dropped at staging for missing `release_id`).
