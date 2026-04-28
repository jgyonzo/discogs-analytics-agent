# Manifest Contract Delta: per-run audit JSON

**Authoritative for**: changes to the manifest JSON shape in this
spec. Read together with the Fase 1 contract at
`specs/001-discogs-etl/contracts/manifest.md`, which remains
authoritative for everything not explicitly diffed here.

**Compatibility promise**: All additions are optional. A Fase 1
manifest (without `step_metrics`) remains valid; a consumer reading
the manifest MUST tolerate the absence of `step_metrics`.

## Top-level shape (delta)

```diff
 {
   "run_id": "...",
   "snapshot_id": "...",
   "etl_version": "...",
   "started_at": "...",
   "finished_at": "...",
   "config": { ... },
   "source_files": { ... },
   "step_durations": { ... },
   "outputs": { ... },
   "quality_checks": { ... },
+  "step_metrics": {
+    "parse_releases": {
+      "peak_rss_bytes": 327680000,
+      "releases_per_sec": 12450.5
+    },
+    "normalize_releases": {
+      "peak_rss_bytes": 332500000,
+      "releases_per_sec": 87123.0
+    },
+    "init_run":         { "peak_rss_bytes": 0,         "releases_per_sec": null },
+    "prepare_sources":  { "peak_rss_bytes": 12000000,  "releases_per_sec": null },
+    "...":              { "peak_rss_bytes": ...,       "releases_per_sec": ... },
+    "finalize_manifest":{ "peak_rss_bytes": 333500000, "releases_per_sec": null }
+  }
 }
```

## `step_metrics` field semantics

A mapping of step name (the same name used in `step_durations`) to
a metrics object:

| Field | Type | Required | Origin | Semantics |
|---|---|---|---|---|
| `peak_rss_bytes` | integer (≥ 0) | yes (per step) | `resource.getrusage(RUSAGE_SELF).ru_maxrss` at step end, normalized to bytes | Cumulative process peak as of step end. Monotonically non-decreasing across steps within a run. |
| `releases_per_sec` | number \| null | yes (per step) | `ProgressReporter.final()` for per-release steps | Average rate over the step. `null` for steps that don't iterate per-release (`init_run`, `prepare_sources`, `quality_checks`, `publish_duckdb`, `finalize_manifest`). |

A step that did NOT run during this invocation (e.g., `publish_duckdb`
on a failed run, or skipped via `--skip-existing`) MAY be omitted
from `step_metrics` entirely.

## New well-known warnings (delta)

Added to `quality_checks.warnings`. Each is a
`{name, details}` object as in Fase 1.

| `name` | Severity-of-source | When |
|---|---|---|
| `parse_releases.truncated_xml` | non-fatal | The XML stream ended mid-element after at least one release was emitted (FR-001). `details` includes the last successful `release_id` and the truncated exception message. |
| `prepare_sources.gz_input` | informational | The chosen input is gzipped — confirms which path was taken. `details` is the input path. |
| `prepare_sources.gz_and_plain_present` | informational | Both `releases.xml` and `releases.xml.gz` exist; uncompressed wins (FR-010). `details` lists both paths. |
| `runtime.peak_rss_exceeds_cap` | informational (**not** a critical failure) | A step's `peak_rss_bytes` exceeded `limits.peak_rss_cap_gib * 2^30` (FR-013). `details` includes the step name and observed peak. |
| `normalize_release_entities.format_quantity_overflow` | informational (**not** a critical failure) | Real Discogs data contains `<format qty>` typos that overflow int64 (e.g., 60-digit integer literals). Such cells are stored as NULL (FR-006). `details` includes the affected row count. *(Retroactively added; fixed in commit `2e6461a`.)* |

The Fase 1 warnings remain unchanged and continue to be emitted
under the same names.

## `quality_checks.status` values (unchanged)

`passed`, `passed_with_warnings`, `failed`, `incomplete` — same as
Fase 1. Note in particular: a truncation warning yields
`passed_with_warnings` (NOT `failed` or `incomplete`).

## `quality_checks.results` entry (unchanged)

Same shape as Fase 1: `{name, layer, table, severity, passed, details}`.
SQL-based check implementations MUST produce results with identical
`name`, `layer`, `table`, `severity`, and `passed` values for the
same input as their in-memory siblings; `details` may differ in
wording.

## Verification

`tests/integration/test_real_sample_pipeline.py` MUST assert the
shape of `step_metrics` and the presence of
`parse_releases.truncated_xml` in `warnings` for the small raw
fixture.

`tests/unit/test_dq_check_parity.py` MUST assert that for every
input where both in-memory and SQL paths are exercised, the
`{name, layer, table, severity, passed}` quintuple is identical.
