# Quickstart: verifying the sandbox file-size budget fix

## 1. The reproducer (failing path, pre-fix)

Against the **full published Discogs DuckDB** at
`./data/published/duckdb/discogs.duckdb`, with the agent stack up
(see `agent/README.md` for bring-up):

```bash
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "show the number of releases over time"}' | jq .
```

**Pre-fix expected (the bug)**:

```json
{
  "status": "failed_validation",
  "execution_result": {
    "exception_type": "IOException",
    "exception_message": "IO Error: Could not write file \"/tmp/duckdb/duckdb_temp_storage_DEFAULT-0.tmp\": File too large",
    "...": "..."
  },
  "final_response": "I generated code but couldn't produce a valid chart after retrying. Try rephrasing.",
  "...": "..."
}
```

**Post-fix expected (the fix)**:

```json
{
  "status": "succeeded",
  "row_count": 14,
  "chart_artifact": { "url": "/artifacts/<uuid>", "type": "plotly_html" },
  "...": "..."
}
```

The chart should be a non-blank line/bar chart of release counts by
decade.

## 2. Verify the new cap is in force

From the agent venv:

```bash
cd agent
source .venv/bin/activate
python -c "from discogs_agent.sandbox.restrictions import RLIMIT_FSIZE_BYTES; print(RLIMIT_FSIZE_BYTES)"
```

Expect:

```
2147483648
```

(That's 2 × 1024³ = 2 GiB.)

## 3. Run the regression test

```bash
pytest tests/integration/test_sandbox_fsize_budget.py -v
```

The test:

- Builds (idempotent) a synthetic spill-forcing DuckDB at
  `agent/tests/fixtures/spill_seed.duckdb` (~5M rows, single
  BIGINT column).
- Invokes the sandbox runner against it with a generated-code-shape
  Python script that does
  `SELECT COUNT(DISTINCT release_id) FROM release_fact GROUP BY g`
  — sized to overflow the pre-fix 64 MiB cap and stay well under
  the new 2 GiB cap.
- Asserts the run succeeds, no `EFBIG`, the result row count
  matches the synthetic data.
- Asserts `RLIMIT_FSIZE_BYTES >= 1 GiB` so a future "tighten the
  cap" change that reverts the fix immediately fails this test.

## 4. Run the existing seed-fixture suite

To confirm the no-regression invariant:

```bash
pytest tests/unit/ tests/integration/ tests/graph/ tests/golden/
```

All previously passing tests MUST still pass.

## 5. Verify no DuckDB mutation (Constitution VI / SC-005)

The existing `tests/integration/test_duckdb_contract.py` already
asserts byte-equality of `seed.duckdb` before/after the integration
suite. Re-run it:

```bash
pytest tests/integration/test_duckdb_contract.py -v
```

Expect: pass.

## 6. (Optional) Smoke against the published DuckDB

If you have a published catalog locally:

```bash
docker compose down
docker compose up --build -d
until curl -fs http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null
do sleep 2
done

# The 005 canonical-style suite — should ALL succeed against the published catalog
for q in "Show Techno releases over time" \
         "House releases by decade" \
         "Drum n Bass releases over time" \
         "Ambient releases by decade" \
         "Trance releases over time" \
         "Dub releases by decade" \
         "Garage releases over time" \
         "Disco releases by decade" \
         "Acid Jazz releases over time" \
         "Funk releases by decade"; do
  status=$(curl -s -X POST http://localhost:8000/query \
    -H 'Content-Type: application/json' \
    -d "{\"message\": \"$q\"}" | jq -r .status)
  echo "$status — $q"
done
```

Expect: 10 out of 10 lines start with `succeeded` (anchors SC-002 of
007 against the published catalog).

## 7. Tear-down

```bash
docker compose down              # stop containers, keep volumes
docker compose down --volumes    # also drop postgres_data + artifacts
```
