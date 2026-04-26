# CLI Contract: Discogs ETL — Fase 1

**Authoritative for**: developer-facing command surface of the `etl/`
component. Realized by `src/discogs_etl/cli.py`.

The CLI is the *only* sanctioned way to run pipeline operations that
produce or modify a layer (Constitution / Development Workflow:
"CLI as the source of truth"). Notebook or REPL invocations are for
inspection only.

## Invocation

```bash
python -m discogs_etl.cli [OPTIONS] COMMAND [COMMAND_ARGS]
```

The package's `__main__.py` calls into `cli.cli()` (a `click.Group`).

### Top-level options

None at this level — all options live on the subcommands so the
contract is explicit per command.

## Subcommands

### `run` — execute the full pipeline

```bash
python -m discogs_etl.cli run --config CONFIG_PATH [OPTIONS]
```

**Required**:
- `--config CONFIG_PATH` (Path) — YAML config file (typically
  `etl/configs/base.yml`). Path is resolved relative to the current
  working directory; use absolute paths in CI.

**Optional**:
- `--run-id RUN_ID` (str) — override the auto-generated run id.
  Auto form is `YYYY-MM-DDTHH-MM-SS` in UTC, sortable. Custom values
  must match `^[A-Za-z0-9._-]+$` (filename-safe).
- `--snapshot-id SNAPSHOT_ID` (str) — override `snapshot_id` from
  the config.
- `--limit-releases N` (int) — stop the parser after the first `N`
  `<release>` elements. Equivalent to truncating the input. Used for
  fast iteration during development; `0` is invalid (use the absence
  of the flag for "no limit").
- `--force` (flag) — allow overwriting outputs in `data/{staging,
  clean,analytics}/{run_id}/` and `data/manifests/{run_id}.json` if
  they already exist. Without `--force` and without `--skip-existing`,
  the run aborts with a clear error before any layer is written.
- `--skip-existing` (flag) — skip steps whose declared outputs
  already exist for the given `run_id`. Mutually compatible with
  `--force`: `--skip-existing` is checked per-step; `--force`
  governs whether *missing* outputs may overwrite a partial state.

**Behavior**:
1. Resolve config + flags → `RunConfig`.
2. Run steps in order (`init_run` → `prepare_sources` →
   `parse_releases` → `normalize_releases` →
   `normalize_release_entities` → `build_release_format_summary` →
   `build_release_fact` → `quality_checks` → `publish_duckdb` →
   `finalize_manifest`).
3. If `quality_checks` reports `status="failed"`, **skip
   `publish_duckdb`** (FR-022). `finalize_manifest` still runs to
   write the failure record.

**Exit status**:
- `0` — `passed` or `passed_with_warnings`.
- `1` — `failed` (critical DQ violation, or any uncaught step
  exception). Manifest written either way; in the
  uncaught-exception case the manifest is finalized as
  `incomplete`.
- `2` — bad CLI usage (missing `--config`, mutually exclusive flag
  combinations the spec does not currently have, etc.).

### `step` — execute a single step

```bash
python -m discogs_etl.cli step STEP_NAME --config CONFIG_PATH [OPTIONS]
```

**Required**:
- `STEP_NAME` (positional) — one of: `init-run`, `prepare-sources`,
  `parse-releases`, `normalize-releases`,
  `normalize-release-entities`, `build-release-format-summary`,
  `build-release-fact`, `quality-checks`, `publish-duckdb`,
  `finalize-manifest`. (Hyphenated; module names use underscores
  but the CLI form is hyphenated for ergonomics.)
- `--config CONFIG_PATH` — same as for `run`.

**Optional**: same set of `--run-id`, `--snapshot-id`,
`--limit-releases`, `--force`, `--skip-existing` as for `run`.
The step subcommand additionally requires that `--run-id` either
references an existing run (steps after `init-run`) or is omitted
when running `init-run` (which generates one).

**Behavior**: Executes the named step against the given run; assumes
prior steps' outputs exist (does not auto-execute prerequisites).
Useful for re-running a single step after a fix without re-parsing
the whole XML.

**Exit status**: same convention as `run` (0 / 1 / 2).

## Exit-status guarantees

- A non-zero exit code MUST be accompanied by a finalized manifest
  whose `quality_checks.status` is `failed` (critical DQ) or
  `incomplete` (uncaught exception). Tests rely on this invariant.
- Exit `0` MUST be accompanied by `quality_checks.status ∈ {passed,
  passed_with_warnings}` and (for `run`) the published DuckDB
  updated by an atomic rename.

## Reserved / forbidden flags

The following names are reserved for future use; current
implementations MUST NOT use them for unrelated semantics:

- `--with-masters` / `--with-artists` — reserved for the Fase 4
  spec's optional flag (Q2 Option C, not chosen but the names are
  off-limits for other purposes).
- `--auto-download` — reserved for Fase 5.

## Logging side effects

Running any subcommand:
- creates / appends to `data/logs/{run_id}.log` (single file per run)
- writes progress messages to stderr at the
  `limits.log_progress_every` cadence configured in `base.yml`

## Out of scope (Fase 1)

- gzipped input handling — no `--gzip` flag in this contract; sample
  XML is uncompressed. (Fase 3.)
- `--dry-run` — not part of this contract; the architecture allows
  for it later (Fase 2 / Fase 3 spec may add it).
- An interactive shell or REPL surface — not part of this CLI; the
  CLI is batch-only.
