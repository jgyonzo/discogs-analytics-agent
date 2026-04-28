# Manifest Contract Delta: Fase 4

**Authoritative for**: changes to the per-run manifest JSON in
this spec. Read together with the Fase 1 contract at
`specs/001-discogs-etl/contracts/manifest.md` (still authoritative
for top-level shape, `quality_checks.status` enum, and the
`outputs.{staging,clean,analytics,published}` blocks) and the
Fase 2+3 delta at `specs/002-etl-scaleup/contracts/manifest.md`
(authoritative for `step_metrics` and the cap-exceeded warning).

**Compatibility promise**: All additions are **optional**. A
manifest produced from a Fase 2+3 release-only snapshot remains a
valid Fase 4 manifest with the addition of two
input-missing warnings (`prepare_sources.masters_missing` /
`prepare_sources.artists_missing`). A consumer reading the
manifest MUST tolerate the absence of any of the new fields.

## Top-level shape (delta)

```diff
 {
   "run_id": "...",
   "snapshot_id": "...",
   "etl_version": "...",
   ...
   "source_files": {
     "releases": { "path": "...", "size_bytes": 0, "checksum": "sha256:..." },
+    "masters":  { "path": "...", "size_bytes": 0, "checksum": "sha256:..." },   // optional
+    "artists":  { "path": "...", "size_bytes": 0, "checksum": "sha256:..." }    // optional
   },
   "step_durations": {
     ...,
+    "parse_masters":         0.0,    // 0.0 when input was missing
+    "parse_artists":         0.0,
+    "normalize_masters":     0.0,
+    "normalize_artists":     0.0,
+    "build_master_fact":     0.0
   },
   "outputs": {
     "staging": {
       ...,
+      "stg_masters":  { "path": "...", "row_count": 0 },   // optional
+      "stg_artists":  { "path": "...", "row_count": 0 }    // optional
     },
     "clean": {
       ...,
+      "clean_masters": { "path": "...", "row_count": 0 },  // optional
+      "clean_artists": { "path": "...", "row_count": 0 }   // optional
     },
     "analytics": {
       ...,
+      "master_fact": {
+        "path": "...",
+        "row_count": 0,
+        "distinct_master_count": 0
+      }                                                      // optional
     },
     "published": {
       "duckdb": {
         "path": "...",
         "published_at": "...",
-        "tables": ["release_fact", "release_artist_bridge", "release_label_bridge"],
+        "tables": ["release_fact", "release_artist_bridge", "release_label_bridge", "master_fact"],   // master_fact appears only when published
         "views":  ["release_unique_view"]
       }
     }
   },
   "step_metrics": {
     ...,
+    "parse_masters":         { "peak_rss_bytes": 0, "releases_per_sec": null },  // releases_per_sec=null for non-release-iterating steps
+    "parse_artists":         { "peak_rss_bytes": 0, "releases_per_sec": null },
+    "normalize_masters":     { "peak_rss_bytes": 0, "releases_per_sec": null },
+    "normalize_artists":     { "peak_rss_bytes": 0, "releases_per_sec": null },
+    "build_master_fact":     { "peak_rss_bytes": 0, "releases_per_sec": null }
   },
   "quality_checks": {
     "status": "passed_with_warnings",
     "warnings": [
       ...,
+      { "name": "prepare_sources.masters_missing",          "details": "..." },  // optional
+      { "name": "prepare_sources.artists_missing",          "details": "..." },  // optional
+      { "name": "parse_masters.truncated_xml",              "details": "..." },  // optional
+      { "name": "parse_artists.truncated_xml",              "details": "..." },  // optional
+      { "name": "build_master_fact.unknown_master_ids",     "details": "..." },  // optional
+      { "name": "build_master_fact.main_release_unresolved","details": "..." },  // optional
+      { "name": "normalize_artists.bridge_unresolved_artists","details":"..." }   // optional
     ],
     "results": [
       ...,
+      // New CheckResult entries (one per Fase 4 critical check that ran)
     ]
   }
 }
```

## New `source_files` entries

When `masters.xml(.gz)` or `artists.xml(.gz)` is present in the
snapshot dir, `prepare_sources` records its path + size + checksum
under the corresponding key, with the same shape as `releases`:

```json
"masters": { "path": "...", "size_bytes": 0, "checksum": "sha256:..." }
```

When absent, the key is omitted entirely AND a
`prepare_sources.masters_missing` warning is added.

## New `step_durations` and `step_metrics` entries

Every Fase 4 step is invoked by the runner regardless of input
presence (R-03). When the step's input is missing, the step
returns early; `step_durations` records the (very small) time
spent and `step_metrics` records `peak_rss_bytes` (typically
unchanged from the prior step) and `releases_per_sec=null`.

When the step actually runs, durations and metrics behave like
their Fase 2+3 siblings.

## New `outputs` entries

`outputs.staging.{stg_masters, stg_artists}`,
`outputs.clean.{clean_masters, clean_artists}`, and
`outputs.analytics.master_fact` are added by the corresponding
steps when they actually write a parquet. When the step returns
early (missing input), the corresponding `outputs.*` entry is
**omitted**.

`outputs.published.duckdb.tables` is the actual list of tables
in the canonical DuckDB after publish, in the order they were
created. `master_fact` appears only when its parquet was
present at publish time.

## New well-known warning names (delta)

| `name` | Source step | Trigger |
|---|---|---|
| `prepare_sources.masters_missing` | prepare_sources | `masters.xml(.gz)` not found in the snapshot dir. `details` is the snapshot path. |
| `prepare_sources.artists_missing` | prepare_sources | `artists.xml(.gz)` not found. |
| `parse_masters.truncated_xml` | parse_masters | `lxml.etree.XMLSyntaxError` raised after at least one full master was emitted. `details` includes the last successful `master_id` and a truncated exception message. |
| `parse_artists.truncated_xml` | parse_artists | Same as above for artists. |
| `build_master_fact.unknown_master_ids` | build_master_fact | `clean_releases.master_id` references master_ids not present in `clean_masters`. `details` includes the count and a few example ids. |
| `build_master_fact.main_release_unresolved` | build_master_fact | `<master>`'s `main_release_id` does not resolve to a row in `release_fact`. `details` includes the count. |
| `normalize_artists.bridge_unresolved_artists` | normalize_artists | `release_artist_bridge.artist_id` references artists not in `clean_artists`. `details` includes the count. |

The Fase 1+2+3 warnings remain unchanged.

## `quality_checks.status` (unchanged)

`passed`, `passed_with_warnings`, `failed`, `incomplete` — same
as Fase 1. Fase 2's "free-standing warnings flip to
passed_with_warnings" rule applies to all the new warning names
above.

## `quality_checks.results` (delta)

New CheckResult names appear in `results` for the Fase 4 checks
listed in `data-model.md`'s "Critical (run fails)" section. Each
follows the same `{name, layer, table, severity, passed, details}`
shape as Fase 1+2+3.

The new SQL siblings of `_check_unique` for the masters/artists
layers MUST return identical
`(name, layer, table, severity, passed)` tuples to their
in-memory siblings (parity guarantee from Fase 2+3 spec FR-014;
the parity test extends to cover them).

## Verification

- `tests/integration/test_masters_artists_pipeline.py` MUST
  assert the new `source_files` keys, the new `outputs` entries,
  the new `step_durations`/`step_metrics` entries, and the
  presence of the published `master_fact` table in
  `outputs.published.duckdb.tables`.
- `tests/integration/test_release_only_snapshot.py` MUST assert
  that the manifest contains the two `prepare_sources.*_missing`
  warnings and that `outputs.analytics.master_fact` is absent.
- `tests/integration/test_real_masters_artists_pipeline.py`
  asserts the truncation warnings
  (`parse_masters.truncated_xml` /
  `parse_artists.truncated_xml`) appear when run against the
  real raw fixtures.
- `tests/unit/test_dq_check_parity.py` extends to cover the new
  SQL siblings.
