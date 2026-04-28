# CLI Contract Delta: Discogs ETL — Fase 4

**Authoritative for**: changes to the developer-facing CLI in this
spec. Read together with the Fase 1 contract at
`specs/001-discogs-etl/contracts/cli.md` (still authoritative for
subcommand shape, exit codes, reserved flags) and the Fase 2+3
delta at `specs/002-etl-scaleup/contracts/cli.md` (still
authoritative for gzip auto-detection and `peak_rss_cap_gib` /
`dq_check_in_memory_threshold` config keys).

**Backward compatibility**: this spec adds **no new flags** and
**no new subcommands**. Per FR-017, all Fase 1+2+3 invocations
continue to work unchanged. The pipeline detects
`masters.xml(.gz)` / `artists.xml(.gz)` in the snapshot
directory automatically, just like Fase 3 detects
`releases.xml.gz`.

## Behavioral changes inside the run

The CLI surface itself is identical, but the run does new things:

- `prepare_sources` now resolves all three optional Discogs XML
  files (`releases`, `masters`, `artists`) using the generalized
  gzip-aware opener. `releases.xml(.gz)` is required (raises if
  missing). `masters.xml(.gz)` and `artists.xml(.gz)` are
  optional — missing inputs emit
  `prepare_sources.masters_missing` / `_artists_missing`
  warnings and the corresponding parse/normalize/build steps
  return early.
- New steps appear in `step_durations` and `step_metrics` (and
  in run logs) when their inputs are present:
  `parse_masters`, `parse_artists`, `normalize_masters`,
  `normalize_artists`, `build_master_fact`. When the inputs are
  absent, the steps are still invoked by the runner (they record
  `step_durations` / `step_metrics`) but they no-op and emit
  no outputs.
- The published DuckDB conditionally adds `master_fact` when its
  parquet exists. Existing tables and views are unchanged.

## Step ordering (pinned by `cli.py`'s STEPS list)

```
init_run
prepare_sources
parse_releases
parse_masters                  ← NEW (conditional)
parse_artists                  ← NEW (conditional)
normalize_releases
normalize_release_entities
normalize_masters              ← NEW (conditional)
normalize_artists              ← NEW (conditional)
build_release_format_summary
build_release_fact
build_master_fact              ← NEW; AFTER build_release_fact
quality_checks
publish_duckdb
finalize_manifest
```

The order matters: `build_master_fact` must run AFTER
`build_release_fact` so the `primary_genre` / `primary_style`
lookups can read `release_fact.parquet` (R-04 in
`research.md`).

## CLI step-name additions

The `step` subcommand's accepted step names map (per Fase 1's
contracts/cli.md `_CLI_TO_INTERNAL`) gain:

```
parse-masters         → parse_masters
parse-artists         → parse_artists
normalize-masters     → normalize_masters
normalize-artists     → normalize_artists
build-master-fact     → build_master_fact
```

These names are reserved at the CLI surface and must be added
verbatim. Existing names from Fase 1 stay unchanged.

## Reserved flags (still off-limits)

Fase 1's reservation list is unchanged:

- `--with-masters` / `--with-artists` — reserved historically;
  Fase 4 deliberately does NOT use them (auto-detection, per
  FR-017). The names remain reserved to prevent collisions.
- `--auto-download` — reserved for Fase 5.

## Out of scope for this spec

- A `--with-masters` / `--with-artists` opt-in flag — auto-detect
  is simpler and cleaner.
- A `--rebuild-master-fact-only` shortcut — use the existing
  `step build-master-fact --run-id <existing> --force` pattern.
- Any agent-facing CLI surface — still in the future agent spec.

## Verification

- All Fase 1 integration tests
  (`test_sample_pipeline.py`) and all Fase 2+3 integration tests
  (`test_real_sample_pipeline.py`,
  `test_big_sample_pipeline.py`) MUST pass unchanged (FR-019 /
  SC-021).
- New tests:
  - `test_masters_artists_pipeline.py` — full pipeline against
    curated tiny fixtures (releases + masters + artists XML).
  - `test_real_masters_artists_pipeline.py` — against the
    user-provided real raw fixtures (317 masters, 4841 artists).
  - `test_release_only_snapshot.py` — explicit backward-compat
    test: snapshot with only `releases.xml` produces the same
    DuckDB shape as Fase 2+3 (no `master_fact` table, two
    missing-input manifest warnings).
