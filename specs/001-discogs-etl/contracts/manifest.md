# Manifest Contract: per-run audit JSON

**Authoritative for**: the JSON shape of `data/manifests/{run_id}.json`.
The manifest is the audit trail mandated by Constitution Principle III
(Reproducible Runs with Manifest & Logs — NON-NEGOTIABLE).

**Source-spec reference**: `docs/discogs_etl_initial_spec.md` § 13.

## Lifecycle

1. Created (empty top-level keys) by `init_run` (Step 0). Atomic
   write: temp file + `os.replace`.
2. Mutated in memory by each step via the `Manifest` helper in
   `discogs_etl/pipeline/manifest.py`. Each step appends to its
   relevant subtree (e.g., `parse_releases` adds an entry under
   `outputs.staging.*`).
3. Persisted to disk after every step (atomic write) so a crash
   leaves an inspectable manifest with `quality_checks.status =
   "incomplete"`.
4. Finalized by `finalize_manifest` (Step 11), which sets
   `finished_at` and reconciles `quality_checks.status`.

## Top-level shape

```json
{
  "run_id": "2026-04-25T10-30-00",
  "snapshot_id": "discogs-2026-04",
  "etl_version": "0.1.0",
  "started_at": "2026-04-25T10:30:00Z",
  "finished_at": "2026-04-25T10:31:42Z",
  "config": {
    "config_path": "etl/configs/base.yml",
    "config_sha256": "..."
  },
  "source_files": {
    "releases": {
      "path": "data/raw/discogs/discogs-2026-04/releases.xml",
      "size_bytes": 0,
      "checksum": "sha256:..."
    }
  },
  "step_durations": {
    "init_run": 0.01,
    "prepare_sources": 0.05,
    "parse_releases": 12.4,
    "normalize_releases": 1.2,
    "normalize_release_entities": 1.0,
    "build_release_format_summary": 0.3,
    "build_release_fact": 0.4,
    "quality_checks": 0.6,
    "publish_duckdb": 0.5,
    "finalize_manifest": 0.01
  },
  "outputs": {
    "staging": {
      "stg_releases":             { "path": "...", "row_count": 0 },
      "stg_release_artists":      { "path": "...", "row_count": 0 },
      "stg_release_labels":       { "path": "...", "row_count": 0 },
      "stg_release_formats":      { "path": "...", "row_count": 0 },
      "stg_release_format_descriptions": { "path": "...", "row_count": 0 },
      "stg_release_genres":       { "path": "...", "row_count": 0 },
      "stg_release_styles":       { "path": "...", "row_count": 0 },
      "stg_release_tracks":       { "path": "...", "row_count": 0 }
    },
    "clean": {
      "clean_releases":           { "path": "...", "row_count": 0 },
      "clean_release_artists":    { "path": "...", "row_count": 0 },
      "clean_release_labels":     { "path": "...", "row_count": 0 },
      "clean_release_formats":    { "path": "...", "row_count": 0 },
      "clean_release_genres":     { "path": "...", "row_count": 0 },
      "clean_release_styles":     { "path": "...", "row_count": 0 },
      "release_format_summary":   { "path": "...", "row_count": 0 }
    },
    "analytics": {
      "release_fact": {
        "path": "...",
        "row_count": 0,
        "distinct_release_count": 0
      },
      "release_artist_bridge":    { "path": "...", "row_count": 0 },
      "release_label_bridge":     { "path": "...", "row_count": 0 }
    },
    "published": {
      "duckdb": {
        "path": "data/published/duckdb/discogs.duckdb",
        "published_at": "2026-04-25T10:31:42Z",
        "tables": ["release_fact", "release_artist_bridge", "release_label_bridge"],
        "views":  ["release_unique_view"]
      }
    }
  },
  "quality_checks": {
    "status": "passed",
    "warnings": [],
    "results": [
      {
        "name": "stg_releases.release_id_not_null",
        "layer": "staging",
        "table": "stg_releases",
        "severity": "critical",
        "passed": true,
        "details": null
      }
    ]
  }
}
```

## Field semantics (selected)

- **`run_id`** — sortable timestamp string; matches the directory
  names in `data/{staging,clean,analytics}/{run_id}/` and the
  manifest's own filename (`{run_id}.json`).
- **`etl_version`** — version string from `etl/pyproject.toml`. Lets
  later runs disambiguate code-generated outputs without consulting
  git.
- **`config.config_sha256`** — sha256 of the resolved config file
  bytes (after CLI overrides are merged is **not** captured here;
  the file content alone is). Lets the user verify "did I change
  the config between runs".
- **`source_files.releases.checksum`** — sha256 of the input
  `releases.xml`. The combination (`config_sha256`,
  `source_files.releases.checksum`, `etl_version`) is the
  reproducibility signature: same triple ⇒ logically equivalent
  outputs (FR-018).
- **`outputs.<layer>.<table>.row_count`** — populated when the
  table's Parquet file is written; `null` if the step did not run.
- **`outputs.analytics.release_fact.distinct_release_count`** —
  populated by `build_release_fact`; consumed by the §12.5
  `COUNT(DISTINCT release_id) == COUNT(clean_releases)` check.
- **`outputs.published.duckdb.published_at`** — set by
  `publish_duckdb` *after* the atomic rename. Absent on a failed
  run (FR-022).

## `quality_checks.status` values

| Value | Meaning |
|---|---|
| `passed` | All checks passed. No warnings recorded. |
| `passed_with_warnings` | All critical checks passed. One or more warnings recorded. Run exits 0. |
| `failed` | At least one critical check failed. Publish skipped. Run exits 1. |
| `incomplete` | The pipeline was interrupted before `quality_checks` ran (e.g., uncaught exception). Publish skipped. Run exits 1. |

## `quality_checks.results` entry

```json
{
  "name": "release_fact.distinct_release_count_equals_clean_releases",
  "layer": "analytics",
  "table": "release_fact",
  "severity": "critical",
  "passed": false,
  "details": "release_fact distinct_release_count = 998 != clean_releases row_count = 1000"
}
```

- `severity` ∈ {`critical`, `warning`} per FR-021 / data-model.md.
- `details` is a free-form string for human inspection. It SHOULD
  be short; if a check produces row-level offending values, prefer
  emitting them to the log file rather than ballooning the manifest.

## Backward / forward compatibility

- This contract is internal to the `etl/` component. No external
  consumer exists in Fase 1 (the agent component does not read the
  manifest in Fase 1; if a future agent does, that introduces a
  new external contract that needs an explicit constitution
  amendment).
- New fields MAY be added in future fases as long as they are
  optional. Existing fields MUST NOT change type.
- A consumer reading the manifest MUST tolerate unknown fields.

## Verification

`etl/tests/integration/test_sample_pipeline.py` MUST assert:
1. Manifest exists at `data/manifests/{run_id}.json` after a run.
2. Top-level keys (`run_id`, `snapshot_id`, `etl_version`,
   `source_files`, `outputs`, `quality_checks`) all present.
3. `quality_checks.status ∈ {"passed", "passed_with_warnings"}` for
   the curated sample fixture.
4. The negative-path test (curated sample with an injected duplicate
   `release_id`) must yield `quality_checks.status == "failed"` and
   `outputs.published.duckdb` MUST NOT be added.
