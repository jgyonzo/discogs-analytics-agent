# `etl/` — Discogs Offline ETL (Fase 1)

This component is the **ETL** half of the project: a local Python CLI that
parses a Discogs `releases.xml` sample in streaming mode, materializes a
layered set of Parquet contracts (staging → clean → analytics), and
publishes a DuckDB at a canonical path that the future analytics agent
component will query.

The component is governed by:

- the project constitution at `.specify/memory/constitution.md`
  (v1.1.0 — Two Components, One Contract),
- the feature spec at `specs/001-discogs-etl/spec.md` (Fase 1 — sample
  vertical slice; clarifications resolved),
- the design artifacts at `specs/001-discogs-etl/{plan,research,data-model,quickstart}.md`
  and `specs/001-discogs-etl/contracts/`.

When the constitution and any local convention disagree, the constitution
prevails.

## Quickstart

From the **repo root**:

```bash
# install editable
pip install -e 'etl/[test]'

# stage a sample input (the curated test fixture works as a smoke target)
mkdir -p data/raw/discogs/discogs-2026-04
cp etl/tests/fixtures/releases_sample.xml data/raw/discogs/discogs-2026-04/releases.xml

# run the full pipeline
python -m discogs_etl.cli run --config etl/configs/base.yml

# inspect the publish target
duckdb data/published/duckdb/discogs.duckdb \
  -c 'SELECT COUNT(DISTINCT release_id) FROM release_fact;'
```

For a step-by-step walkthrough including the failure-path validation
(FR-022 / SC-006 — critical DQ failure must leave the canonical published
DuckDB byte-identical), see
`specs/001-discogs-etl/quickstart.md`.

## CLI

The full CLI contract is at `specs/001-discogs-etl/contracts/cli.md`.
Quick reference:

```bash
python -m discogs_etl.cli run  --config etl/configs/base.yml [OPTIONS]
python -m discogs_etl.cli step <step-name> --config etl/configs/base.yml [OPTIONS]
```

Options:

| Flag | Purpose |
|---|---|
| `--config PATH` | YAML config (required) |
| `--run-id ID` | Override the auto-generated run id |
| `--snapshot-id ID` | Override `snapshot_id` from config |
| `--limit-releases N` | Stop after N `<release>` elements |
| `--force` | Allow overwriting outputs at an existing run id |
| `--skip-existing` | Skip steps whose declared outputs already exist |

## Tests

```bash
pytest etl/tests/         # all 54 tests, ~0.3s on a developer laptop
```

The integration test (`etl/tests/integration/test_sample_pipeline.py`)
runs the full pipeline against the curated fixture for both the happy
path and the FR-022/SC-006 failure path — i.e., it asserts that on a
critical DQ failure (duplicate `release_id`) the canonical published
DuckDB is left byte-identical to its prior state.

## Where things live

- `etl/src/discogs_etl/` — package source
  - `cli.py` — click-based CLI; entrypoint
  - `pipeline/` — runner, manifest, run context + logging
  - `steps/` — one file per pipeline step; each implements the `Step` protocol
  - `parsers/releases_parser.py` — streaming `lxml.iterparse`
  - `transforms/` — pure functions (date, format, text normalization)
  - `io/` — Parquet writer, DuckDB publisher, schemas, file helpers
  - `quality/` — §12 data-quality checks and aggregation
- `etl/configs/base.yml` — default config
- `etl/tests/` — unit tests + integration test + curated fixtures
  - `etl/tests/fixtures/releases_sample.xml` — 7 curated releases (in-scope edges)
  - `etl/tests/fixtures/releases_sample_bad.xml` — duplicate `release_id` for FR-022 test
  - `etl/tests/fixtures/releases_sample_raw.xml` — 404-release real Discogs excerpt (reference; truncated, not used by tests)

## Out of scope (deferred to follow-up specs)

- Real-world XML variability beyond the curated sample (Fase 2).
- Full-dump scale / gzip / mid-run kill / RSS benchmark (Fase 3).
- Masters / artists XML, `master_fact`, `artist_dim` (Fase 4).
- Auto-download from Discogs (Fase 5).
- AWS execution / agent component (separate `agent/` component, future spec).
