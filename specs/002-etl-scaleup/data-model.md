# Phase 1 Data Model: Discogs ETL — Fase 2+3

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Authoritative for**: changes to operational entities and the
manifest. Layer table contracts are unchanged from Fase 1; this
document does not restate them.

The Fase 1 data model (`specs/001-discogs-etl/data-model.md`) is
still the authoritative source for staging / clean / analytics /
published table contracts. Read it together with this document.

## What's unchanged

- Snapshot, Run, Release, Style/Genre/Format/Artist/Label entities.
- All staging / clean / analytics table schemas (source spec
  §6/§7/§8/§9, anchored in Fase 1's `data-model.md`).
- Published DuckDB schema (Fase 1's `contracts/duckdb-schema.md`).
- Critical-vs-warning DQ classification (FR-021 from Fase 1, still
  binding).

## What's new in this spec

### Step metrics *(new)*

A per-step metrics record that the runner emits at the end of each
step.

| Field | Type | Origin | Notes |
|---|---|---|---|
| `peak_rss_bytes` | integer | `resource.getrusage(RUSAGE_SELF).ru_maxrss` (with platform unit conversion) | Cumulative process peak as of step end. Monotonically non-decreasing across steps within a run. |
| `releases_per_sec` | float \| null | computed in `ProgressReporter.final()` from per-release step | `null` for steps that don't iterate per-release (init_run, prepare_sources, publish_duckdb, finalize_manifest, quality_checks). |

Lives at `manifest.step_metrics.{step_name}.{field}` per
`contracts/manifest.md`.

### New well-known warnings

These names are reserved and consistent across the codebase:

| Warning name | Source step | Trigger |
|---|---|---|
| `parse_releases.truncated_xml` | parse_releases | `lxml.etree.XMLSyntaxError` raised after at least one full release was emitted (FR-001). Details include last successful `release_id`. |
| `prepare_sources.gz_and_plain_present` | prepare_sources | Both `releases.xml` and `releases.xml.gz` exist in the snapshot dir; uncompressed wins (FR-010). |
| `prepare_sources.gz_input` | prepare_sources | The chosen input is gzipped — informational, lets the developer confirm which path was taken. |
| `runtime.peak_rss_exceeds_cap` | runner / finalize_manifest | A step's `peak_rss_bytes` exceeded `limits.peak_rss_cap_gib * 2^30` (FR-013). Informational, not a failure. |
| `normalize_release_entities.format_quantity_overflow` | normalize_release_entities | A `<format qty>` attribute parsed as an integer outside int64 range (FR-006); cell stored as NULL. `details` includes the count. *(Retroactively added after the April 2026 full-dump run; fixed in commit `2e6461a`.)* |

The Fase 1 warnings (`parse_releases.dropped_no_release_id`,
`normalize_release_entities.unmapped_format_names`,
`normalize_releases.invalid_dates`) remain valid and unchanged.

### DQ-check dispatch *(new behavioral entity)*

`quality.dispatch.run_check` selects between an in-memory and a
SQL-based implementation of the same check based on the source
Parquet's row count. Both implementations MUST return a
`CheckResult` whose `name`, `layer`, `table`, `severity`, and
`passed` fields are identical for the same input.

| Decision input | Source |
|---|---|
| Row count of the Parquet under check | `pyarrow.parquet.read_metadata(path).num_rows` (cheap, no data load) |
| Threshold | `config.limits.dq_check_in_memory_threshold` (default 10_000_000) |
| In-memory function | existing `quality.checks._check_*` (Counter / set based) |
| SQL function | new `quality.checks._check_*_sql` (DuckDB queries) |

Checks that are dispatched (Fase 1 paths get an SQL sibling):

| Check | In-memory | SQL alternative |
|---|---|---|
| Uniqueness on a single column | `Counter(arr).items() with count > 1` | `SELECT col FROM read_parquet(...) GROUP BY col HAVING COUNT(*) > 1 LIMIT 5` |
| Pair uniqueness | `Counter(zip(c1, c2))` | `SELECT c1, c2 FROM ... GROUP BY 1,2 HAVING COUNT(*) > 1 LIMIT 3` |
| At-most-one-primary | `Counter` with predicate | `SELECT group_col FROM ... WHERE flag_col GROUP BY 1 HAVING COUNT(*) > 1 LIMIT 5` |
| Distinct count == reference | `len(set(arr))` | `SELECT COUNT(DISTINCT col) FROM ...` |

Checks that **don't** need an SQL sibling (already O(1) memory or
trivially bounded): `_check_no_null` (uses pyarrow's `null_count`
column metadata), `_check_in_set` (small enum), `_check_min_value`
(streaming sum). These keep their Fase 1 implementation; the
dispatcher passes through.

## Configuration additions

`etl/configs/base.yml` gains two `limits.*` keys:

```yaml
limits:
  parser_batch_size: 50000              # unchanged
  log_progress_every: 10000             # unchanged
  peak_rss_cap_gib: 4                   # NEW
  dq_check_in_memory_threshold: 10000000 # NEW
```

`pipeline.context.LimitConfig` gains the two fields with the same
defaults. Old `base.yml` files without these keys keep working.

## Manifest extension contract

Authoritative form lives in [contracts/manifest.md](./contracts/manifest.md).
Summary diff vs Fase 1:

```diff
 {
   "run_id": "...",
   "snapshot_id": "...",
   ...
   "outputs": { ... },
   "quality_checks": { ... },
+  "step_metrics": {
+    "parse_releases": {
+      "peak_rss_bytes": 327680000,
+      "releases_per_sec": 12450.5
+    },
+    "normalize_releases": { "peak_rss_bytes": 332500000, "releases_per_sec": 87123.0 },
+    ...
+  }
 }
```

`step_metrics` is **optional** and additive: a Fase 1 manifest
without `step_metrics` remains valid.

## Where this differs from / extends the source spec

- The source design doc (`docs/discogs_etl_initial_spec.md`) does
  not enumerate per-step memory metrics; this is a Fase 3
  observability addition motivated by SC-011 / SC-013 in spec.md.
- The DQ-dispatch behavior is also a Fase 2+3 addition; the source
  doc treats §12 as a single check pass.
- All schema and contract additions are **additive**: nothing from
  Fase 1 is removed or redefined.

## Out of scope (per Q1=B, Q2=B)

- Master / artist tables (Fase 4 spec).
- Auto-download from Discogs (Fase 5 spec).
- Wall-clock budgets enforced as gates (FR-013 makes peak RSS a
  warning, not a gate; we do not introduce a wall-clock gate).
- DuckDB-engine tuning (parallelism, memory limit) — defaults
  suffice for the in-repo big_raw fixture.
