# Quickstart: Discogs ETL — Fase 4

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Audience**: a developer on this branch who wants to verify Fase
4's master analytics + the artists-pipeline foundation, plus the
backward-compat behavior on a release-only snapshot.

This walkthrough assumes the implementation tasks (produced by
`/speckit-tasks` in a follow-up step) are complete. It doubles as
the manual integration script.

---

## 0. Prerequisites

- Python 3.11+ (3.12 recommended).
- macOS or Linux. Windows still not validated.
- The Fase 1+2+3 install is sufficient: from the repo root,
  `pip install -e 'etl/[test]'` brings in everything (no new
  runtime deps in this spec).
- The Fase 4 raw fixtures are tracked in git:
  - `etl/tests/fixtures/masters_sample_raw.xml` (664 KB, 317
    masters, truncated mid-element).
  - `etl/tests/fixtures/artists_sample_raw.xml` (3.7 MB, 4841
    artists, truncated mid-element).

## 1. Smoke: Fase 1+2+3 still works (regression check)

The Fase 1 / Fase 2+3 fixtures and tests must keep passing
unchanged:

```bash
pytest etl/tests/integration/test_sample_pipeline.py \
       etl/tests/integration/test_real_sample_pipeline.py -v
```

All prior acceptance scenarios should still pass (FR-019 / SC-021).

## 2. Curated tiny snapshot (releases + masters + artists)

Stage the curated samples (releases + masters + artists) under a
single snapshot dir:

```bash
mkdir -p data/raw/discogs/discogs-2026-04
cp etl/tests/fixtures/releases_sample.xml \
   data/raw/discogs/discogs-2026-04/releases.xml
cp etl/tests/fixtures/masters_sample.xml \
   data/raw/discogs/discogs-2026-04/masters.xml
cp etl/tests/fixtures/artists_sample.xml \
   data/raw/discogs/discogs-2026-04/artists.xml

python -m discogs_etl.cli run --config etl/configs/base.yml ; echo "exit=$?"
```

Expected:

- `exit=0`.
- `quality_checks.status = "passed"` or `"passed_with_warnings"`
  (curated samples may include some intentional warning
  triggers).
- The latest manifest at `data/manifests/{run_id}.json` records:
  - `source_files.{releases, masters, artists}` all present.
  - `step_durations.{parse_masters, parse_artists,
    normalize_masters, normalize_artists, build_master_fact}` all
    populated.
  - `outputs.staging.{stg_masters, stg_artists}` /
    `outputs.clean.{clean_masters, clean_artists}` /
    `outputs.analytics.master_fact` all present.
  - `outputs.published.duckdb.tables` contains
    `["release_fact", "release_artist_bridge",
    "release_label_bridge", "master_fact"]`.

Validate the published DuckDB:

```bash
duckdb data/published/duckdb/discogs.duckdb <<'SQL'
SELECT COUNT(*) AS masters FROM master_fact;
SELECT title, release_count, primary_genre, primary_style
FROM master_fact
ORDER BY release_count DESC LIMIT 5;
-- cross-table consistency (FR-015 / SC-003):
SELECT (SELECT SUM(release_count) FROM master_fact) AS sum_,
       (SELECT COUNT(*) FROM release_fact)           AS rf_with_master_id_rows;
SQL
```

Expected: `master_fact` row count matches the count of distinct
master_ids in the union of `clean_masters` and
`clean_releases.master_id WHERE NOT NULL`. The sum-equals check
holds. `primary_genre` / `primary_style` are populated for masters
whose `main_release_id` resolves to a release in `release_fact`.

## 3. Real raw fixtures (truncation handling for masters / artists)

Stage the real raw fixtures (already committed):

```bash
mkdir -p data/raw/discogs/discogs-2026-04
cp etl/tests/fixtures/releases_sample_raw.xml \
   data/raw/discogs/discogs-2026-04/releases.xml
cp etl/tests/fixtures/masters_sample_raw.xml \
   data/raw/discogs/discogs-2026-04/masters.xml
cp etl/tests/fixtures/artists_sample_raw.xml \
   data/raw/discogs/discogs-2026-04/artists.xml

python -m discogs_etl.cli run --config etl/configs/base.yml --run-id real-fase4 ; echo "exit=$?"
```

Expected:

- `exit=0`.
- `quality_checks.status = "passed_with_warnings"` (truncation
  warnings expected for all three XMLs).
- Manifest's `quality_checks.warnings` contains
  `parse_releases.truncated_xml`,
  `parse_masters.truncated_xml`, and
  `parse_artists.truncated_xml`.
- DuckDB `SELECT COUNT(*) FROM master_fact` ≈ 317 (plus any
  orphan master_ids referenced by clean_releases that aren't in
  clean_masters — the union is the canonical set).
- Cross-table consistency holds: `SUM(release_count) =
  COUNT(clean_releases WHERE master_id IS NOT NULL)`.

## 4. Backward-compat: release-only snapshot

Re-stage the original Fase 1/2+3 release-only snapshot (no
masters / artists XML present):

```bash
rm -f data/raw/discogs/discogs-2026-04/masters.xml \
      data/raw/discogs/discogs-2026-04/artists.xml \
      data/raw/discogs/discogs-2026-04/masters.xml.gz \
      data/raw/discogs/discogs-2026-04/artists.xml.gz

python -m discogs_etl.cli run --config etl/configs/base.yml --run-id release-only ; echo "exit=$?"
```

Expected:

- `exit=0` (releases are present; missing masters/artists are
  warnings, not failures).
- Manifest's `quality_checks.warnings` contains
  `prepare_sources.masters_missing` and
  `prepare_sources.artists_missing`.
- `outputs.analytics.master_fact` is **absent** from the
  manifest.
- The published DuckDB contains exactly
  `release_fact` / `release_artist_bridge` /
  `release_label_bridge` and the `release_unique_view` view —
  byte-stable with Fase 2+3.
- `step_durations` records very small durations for the
  conditional steps (they returned early).

## 5. Failure path: duplicate `master_id`

To exercise the FR-022 / SC-006 flavor for the new layer, stage
the bad master fixture (a `masters_sample_bad.xml` with a
duplicate `master_id` will be created in the implementation
phase):

```bash
cp etl/tests/fixtures/masters_sample_bad.xml \
   data/raw/discogs/discogs-2026-04/masters.xml
python -m discogs_etl.cli run --config etl/configs/base.yml --run-id bad-master ; echo "exit=$?"
```

Expected:

- `exit=1`.
- Manifest's `quality_checks.status = "failed"`; results include
  `stg_masters.master_id_unique` failing or
  `clean_masters.master_id_unique` failing.
- `outputs.analytics.master_fact` is absent (publish step skipped
  per FR-022 inheritance from Fase 1).
- The canonical published DuckDB at
  `data/published/duckdb/discogs.duckdb` is **byte-identical**
  to its prior state.

## 6. Run the test suite

```bash
# Unit + Fase 1/2+3 + new Fase 4 integration. Skips the gated
# big-fixture test from spec 002 unless DISCOGS_BIG_FIXTURE=1.
pytest etl/tests/

# Fase 3 big-fixture (gated):
DISCOGS_BIG_FIXTURE=1 pytest etl/tests/integration/test_big_sample_pipeline.py
```

Expected: every prior test still passes (SC-021), every new
Fase 4 test passes too. The new tests:

- `tests/unit/test_master_parser.py`
- `tests/unit/test_artist_parser.py`
- `tests/unit/test_master_fact_builder.py`
- `tests/unit/test_dq_check_parity.py` (extended to cover
  Fase 4 SQL siblings)
- `tests/integration/test_masters_artists_pipeline.py`
- `tests/integration/test_real_masters_artists_pipeline.py`
- `tests/integration/test_release_only_snapshot.py`

## 7. The agent's "top techno works" canonical query

After step 2 or step 3 publishes, the agent's master-level
canonical query runs against the new surface:

```sql
SELECT title, release_count
FROM master_fact
WHERE primary_style = 'Techno'
ORDER BY release_count DESC
LIMIT 10;
```

If the snapshot includes Techno-styled masters (the curated
fixtures may not; the real raw sample very likely does), the
result lists their reissue counts.

## 8. What's NOT in this spec

If any of the below doesn't yet work, that's **by design** —
deferred to follow-up specs:

- `artist_dim` table in DuckDB. `clean_artists.parquet` is
  produced as the foundation; the future `artist_dim` spec adds
  the DuckDB surface.
- `release_genre_bridge` for multi-genre exact analysis (source
  spec §18.2).
- `company_bridge` for pressing / studio analysis (§18.4).
- A `master_id` denorm column on `release_fact` — would require
  a constitution amendment.
- Auto-download from Discogs (Fase 5).
- The agent component.

## 9. Cleanup between runs

Each run uses its own `run_id` directories under
`data/{staging,clean,analytics}/`, so re-running doesn't collide.
To free disk between iterations:

```bash
rm -rf data/staging data/clean data/analytics data/manifests data/logs
# leave data/published/duckdb/discogs.duckdb (the canonical publish)
# unless you want to verify FR-022 byte-identical-on-failure
# behavior as in Fase 1.
```
