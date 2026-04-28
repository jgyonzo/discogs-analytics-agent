# DuckDB Schema Contract Delta: Fase 4 published surface

**Authoritative for**: changes to the published DuckDB in this
spec. Read together with the Fase 1 contract at
`specs/001-discogs-etl/contracts/duckdb-schema.md`, which
remains authoritative for the unchanged release-side tables and
view.

**Compatibility promise**: All additions are *additive*. A
consumer of the Fase 1 contract that reads only
`release_fact`, `release_artist_bridge`, `release_label_bridge`,
and `release_unique_view` continues to work without modification.
Per the Fase 1 stability promise:

> Fase 4 (masters / artists): MAY add new tables (e.g.,
> `master_fact`, `artist_dim`). Existing columns / grain on
> `release_fact` and bridges remain stable. New columns on
> existing tables (e.g., a `master_id` denorm) require a
> constitution amendment for the published-surface change.

This spec adds **`master_fact`** only. `artist_dim` is deferred
per Q1=B. No existing-table modifications.

## Surface (delta)

### New tables

| Name | Grain | Conditional |
|---|---|---|
| `master_fact` | one row per master_id (∪ of `clean_masters` ∪ `clean_releases.master_id`) | Yes — published only when `data/analytics/{run_id}/master_fact.parquet` exists, i.e., when `masters.xml(.gz)` was present in the snapshot |

### Unchanged

`release_fact`, `release_artist_bridge`, `release_label_bridge`,
and the view `release_unique_view` keep their Fase 1 shapes
exactly.

## `master_fact` schema

| Column | Type | Nullable | Source |
|---|---|---|---|
| `master_id` | BIGINT | No | clean_masters or clean_releases (primary key) |
| `title` | TEXT | Yes | clean_masters (NULL for orphan-from-releases rows) |
| `main_release_id` | BIGINT | Yes | clean_masters |
| `year` | INTEGER | Yes | clean_masters (parsed from year_raw) |
| `decade` | INTEGER | Yes | derived: `(year // 10) * 10` when year is set |
| `release_count` | INTEGER | No | aggregate of `clean_releases.master_id = m.master_id`; `0` for orphan masters |
| `earliest_year` | INTEGER | Yes | `MIN(clean_releases.year)` for that master; NULL when no resolved releases |
| `latest_year` | INTEGER | Yes | `MAX(clean_releases.year)` for that master; NULL when no resolved releases |
| `primary_genre` | TEXT | Yes | `release_fact.primary_genre` for the row whose `release_id = m.main_release_id`; NULL when `main_release_id` is missing or doesn't resolve |
| `primary_style` | TEXT | Yes | `release_fact.style` for the row whose `release_id = m.main_release_id` AND `style_order = 1`; NULL when not resolvable |
| `run_id` | TEXT | No | this run's id |

## Counting / joining rules (NORMATIVE — agent-facing)

- **Unique masters** are counted via
  `SELECT COUNT(*) FROM master_fact` (master_id is the primary
  key — every distinct master gets one row).
- **Releases per master** is `master_fact.release_count`. Use
  this directly; do NOT compute `COUNT(DISTINCT release_id)
  FROM release_fact GROUP BY master_id` unless you need a sanity
  check.
- **Joining `master_fact` to `release_fact`** is performed on
  `master_id`. Note: `release_fact` is row-multiplied by style
  (Fase 1's grain), so a join may produce one row per
  release × style. Use `release_unique_view.master_id` for
  release-grain joins.
- **Top works by reissue count**:
  ```sql
  SELECT title, release_count
  FROM master_fact
  ORDER BY release_count DESC
  LIMIT 10;
  ```
- **Top "techno works" by reissue count**:
  ```sql
  SELECT title, release_count
  FROM master_fact
  WHERE primary_style = 'Techno'
  ORDER BY release_count DESC
  LIMIT 10;
  ```
- **Earliest / latest year for a master**:
  ```sql
  SELECT title, earliest_year, latest_year
  FROM master_fact
  WHERE master_id = ?;
  ```

## Naming-convention guarantees

The Fase 1 load-bearing names (`is_*_format` at format grain;
`has_*` at release grain; `release_unique_view` for
unique-release counts) carry forward unchanged. New names
introduced here:

- `master_fact.release_count` — agent-facing aggregate per
  master.
- `master_fact.earliest_year` / `latest_year` — agent-facing
  bounds per master.
- `master_fact.primary_genre` / `primary_style` — derived from
  `release_fact.primary_genre` and `release_fact.style` at the
  master's `main_release_id` (style_order = 1).

These names are **stable** going forward — future specs MUST NOT
rename them without a constitution amendment.

## Stability promise (Fase 4 → Fase 5+)

- **Fase 4 (this spec)**: `master_fact` schema as defined above;
  `artist_dim` deferred.
- **Future `artist_dim` spec**: MAY add `artist_dim` as a new
  table. MUST NOT alter `master_fact`'s columns or grain.
- **Future Fase 5 (downloader)**: schema unchanged; just adds an
  upstream step.
- A `master_id` denorm column on `release_fact` (or a
  `master_title` denorm) would require a constitution amendment.

## Out of scope (Fase 4)

- `artist_dim` (Q1=B; future spec).
- `release_genre_bridge` (source spec §18.2).
- `company_bridge` (source spec §18.4).
- Any indexing or DuckDB-specific physical layout guidance —
  consumers MUST treat the DB as a logical schema only.

## Verification

`tests/integration/test_masters_artists_pipeline.py` MUST
assert, against the produced DuckDB:

1. The five published objects exist:
   `release_fact`, `release_artist_bridge`,
   `release_label_bridge`, `master_fact`, and the
   `release_unique_view` view.
2. `master_fact` columns match the schema above
   (`SELECT * FROM master_fact LIMIT 0` verifies column names
   and types).
3. `SELECT COUNT(*) FROM master_fact` matches the count of
   distinct master_ids in the union
   (`clean_masters ∪ clean_releases.master_id WHERE NOT NULL`).
4. `SELECT SUM(release_count) FROM master_fact` equals
   `SELECT COUNT(*) FROM clean_releases WHERE master_id IS NOT NULL`
   (FR-015 cross-table consistency check; SC-003).
5. For at least one master with a resolved
   `main_release_id`, `primary_genre` / `primary_style` match
   the values in `release_fact` for the corresponding release_id
   at `style_order = 1` (SC-004).

`tests/integration/test_release_only_snapshot.py` MUST assert
that on a snapshot lacking `masters.xml`:

1. The published DuckDB does NOT contain `master_fact` (only
   the four Fase 1 objects exist).
2. The manifest's `outputs.published.duckdb.tables` list is
   exactly `["release_fact", "release_artist_bridge",
   "release_label_bridge"]`.
3. The manifest's `quality_checks.warnings` includes
   `prepare_sources.masters_missing`.
