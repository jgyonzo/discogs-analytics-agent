# Quickstart: Discogs ETL — Fase 1

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Audience**: a developer who just cloned the repo (or just merged
this branch) and wants to produce a published DuckDB from a sample
`releases.xml`.

This walkthrough assumes Fase 1 implementation is complete (i.e., it
describes the behavior `/speckit-tasks` and `/speckit-implement` will
deliver). It doubles as the manual integration script.

---

## 0. Prerequisites

- Python 3.11+ (3.12 recommended; the project venv is 3.12.12).
- macOS or Linux. Windows not validated for Fase 1.
- A small `releases.xml` sample. If you don't have one yet, the
  committed fixture at `etl/tests/fixtures/releases_sample.xml`
  works for the smoke test.

## 1. Set up the environment

From the repo root:

```bash
# reuse the existing venv at .venv/, or create one
python3.12 -m venv .venv
source .venv/bin/activate

# install the etl/ component editable
pip install -e etl/
```

The `pip install -e etl/` reads `etl/pyproject.toml` and pulls in
`lxml`, `pyarrow`, `duckdb`, `click`, `PyYAML`, `pytest`.

Verify the CLI is reachable:

```bash
python -m discogs_etl.cli --help
```

## 2. Place a sample input

Pick a `snapshot_id` (any filename-safe string; recommended:
`discogs-2026-04` or similar dated id). Place the sample releases
XML at the conventional path:

```bash
mkdir -p data/raw/discogs/discogs-2026-04
cp etl/tests/fixtures/releases_sample.xml \
   data/raw/discogs/discogs-2026-04/releases.xml
```

Or, point a real Discogs sample at this path. Gzipped input is not
supported in Fase 1 — decompress first.

## 3. Inspect / edit the config

`etl/configs/base.yml` looks like:

```yaml
snapshot_id: discogs-2026-04
paths:
  raw_dir: data/raw/discogs
  staging_dir: data/staging
  clean_dir: data/clean
  analytics_dir: data/analytics
  published_duckdb: data/published/duckdb/discogs.duckdb
  manifests_dir: data/manifests
  logs_dir: data/logs
limits:
  parser_batch_size: 50000
  log_progress_every: 10000
```

For a tiny sample run, you can leave `parser_batch_size` and
`log_progress_every` at their defaults — they only affect cadence,
not correctness.

## 4. Run the pipeline

End-to-end, smallest invocation:

```bash
python -m discogs_etl.cli run --config etl/configs/base.yml
```

For an even smaller dry-run on the head of the file:

```bash
python -m discogs_etl.cli run \
  --config etl/configs/base.yml \
  --limit-releases 100
```

You'll see progress messages on stderr; the same lines (and more)
land in `data/logs/{run_id}.log`. The auto-assigned `run_id` is
printed at startup; capture it if you want to rerun against the
same outputs.

Expected wall-clock on the committed fixture (≈5 releases): under
~2 seconds. On a 1000-release sample: under 60 seconds (SC-004).

## 5. Verify the outputs

```bash
# Outputs of the most recent run (replace <run_id> with the value
# printed in the log; or sort the manifests dir).
ls data/staging/<run_id>/
ls data/clean/<run_id>/
ls data/analytics/<run_id>/
cat data/manifests/<run_id>.json | jq .quality_checks.status
```

Expect `"passed"` or `"passed_with_warnings"`. Then peek at the
published DuckDB:

```bash
duckdb data/published/duckdb/discogs.duckdb <<'SQL'
SELECT COUNT(DISTINCT release_id) AS releases FROM release_fact;
SELECT COUNT(*) FROM release_unique_view;
SELECT * FROM release_fact LIMIT 5;
SQL
```

The two counts should be equal and should equal the number of
`<release>` elements in your input (modulo any rejected at
staging — see warnings).

## 6. The canonical agent query

The query the future analytics agent component is meant to be able
to generate, against this exact DB:

```sql
SELECT decade, COUNT(DISTINCT release_id) AS releases
FROM release_fact
WHERE style = 'Techno' AND decade IS NOT NULL
GROUP BY decade
ORDER BY decade;
```

If your sample has no Techno-styled releases the result will be
empty — that's fine; the test is that the query *runs* against the
v1 contract.

## 7. Failure path: what happens if a critical DQ check fails

To exercise FR-022 / SC-006:

```bash
# Use the curated bad-sample fixture (committed alongside the good
# one) which contains a duplicated release_id.
cp etl/tests/fixtures/releases_sample_bad.xml \
   data/raw/discogs/discogs-2026-04/releases.xml

python -m discogs_etl.cli run --config etl/configs/base.yml ; echo "exit=$?"
```

Expected:

- `exit=1`
- `data/manifests/{run_id}.json` records
  `quality_checks.status = "failed"` and the offending check name.
- `data/published/duckdb/discogs.duckdb` is **byte-identical** to
  whatever it was before the failed run (or absent if there was no
  prior good publish).

## 8. Re-running

- **Skip already-complete steps** (fast iteration on a fix in the
  later steps):

  ```bash
  python -m discogs_etl.cli run \
    --config etl/configs/base.yml \
    --run-id <previous_run_id> \
    --skip-existing
  ```

- **Force overwrite an existing run** (e.g., to re-parse from
  scratch with the same id):

  ```bash
  python -m discogs_etl.cli run \
    --config etl/configs/base.yml \
    --run-id <previous_run_id> \
    --force
  ```

- **Run a single step** (after fixing a bug in, say, the format
  normalizer):

  ```bash
  python -m discogs_etl.cli step normalize-release-entities \
    --config etl/configs/base.yml \
    --run-id <previous_run_id> \
    --force
  ```

  Then re-run subsequent steps in order, or invoke `run` with
  `--skip-existing` to pick up where the manual step finished.

## 9. Running the test suite

```bash
pytest etl/tests/
```

Expected: unit tests over transforms and DQ checks pass; the
integration test runs the full pipeline against
`etl/tests/fixtures/releases_sample.xml` and asserts on the
resulting DuckDB and manifest.

A failing integration test should be the first place to look when a
change to a step produces unexpected DuckDB output.

## 10. What's NOT in this Fase

If any of the following don't work yet, that is **by design** —
they are deferred to follow-up specs:

- Gzip-compressed input (Fase 3).
- Robustness against arbitrary real-world XML variability beyond the
  curated sample (Fase 2).
- The full ~60GB Discogs releases dump on a laptop with bounded RSS
  benchmarked (Fase 3).
- `masters.xml` / `artists.xml` parsing, `master_fact`, `artist_dim`
  (Fase 4).
- Auto-download from Discogs (Fase 5).

When you want any of those, start a new `/speckit-specify`.
