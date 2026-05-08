# Quickstart: JSONB NaN sanitization

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Executable companion to the spec. Three sections: pre-fix reproducer, post-fix verification, and the regression-test invocation.

---

## 1. Manual reproducer (live agent)

Pre-fix, the agent 500s on any query whose dataframe preview contains a NULL cell.

### 1.1 Setup

```bash
docker compose up agent-api postgres
curl -fs http://localhost:8000/health | jq .
```

### 1.2 Submit the canonical reproducer

```bash
curl -i -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"message": "What are the top 15 countries by number of releases?"}'
```

**Pre-fix expected output**: HTTP 500 with `error.code: "internal_error"`. The agent log shows:

```
postgres-1  | ERROR:  invalid input syntax for type json
postgres-1  | DETAIL:  Token "NaN" is invalid.
agent-api-1 | psycopg.errors.InvalidTextRepresentation
```

**Post-fix expected output**: HTTP 200 with a populated `chart_artifact`, `dataframe_preview` (JSON-valid; NULL cells appear as JSON `null`, not `NaN`), and `status: "succeeded"`.

### 1.3 SC-001 / SC-002 manual gate

Run the reproducer 10 times against the live agent post-fix:

```bash
PASS=0; FAIL=0
for i in $(seq 1 10); do
  status=$(curl -fs -X POST http://localhost:8000/query \
    -H 'Content-Type: application/json' \
    -d '{"message": "What are the top 15 countries by number of releases?"}' \
    -o /tmp/r.json -w '%{http_code}')
  if [ "$status" = "200" ] && jq -e '.status == "succeeded"' /tmp/r.json >/dev/null; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
  fi
done
echo "PASS=$PASS FAIL=$FAIL"
```

**Pass criteria** (post-fix): `PASS >= 9` (SC-001 — allows for cheap-model variance on incidental wording). Postgres logs MUST show zero `InvalidTextRepresentation` messages across all 10 attempts (SC-002).

---

## 2. Inspect a tool-call row's `output_json`

To eyeball that NULL cells are stored as JSON `null` (not `NaN`):

```bash
docker exec -it $(docker compose ps -q postgres) \
  psql -U agent -d agent -c \
  "SELECT jsonb_pretty(output_json) FROM agent_tool_calls
   WHERE tool_name = 'sandbox_executor'
   ORDER BY created_at DESC LIMIT 1;"
```

Look for `null` in cells where the dataframe had missing values. If you see `NaN`, the fix didn't fire. If the column is missing entirely, the row predates the fix.

---

## 3. Run the regression test

```bash
cd agent
.venv/bin/pytest tests/unit/test_jsonb_sanitizer.py tests/integration/test_jsonb_nan_persistence.py -v
```

Expected: all green post-fix.

To verify the test catches the bug, temporarily revert the fix:

```bash
git stash push -m "test reverting 010 fix" \
  agent/src/discogs_agent/persistence/models.py \
  agent/src/discogs_agent/persistence/sanitize.py
.venv/bin/pytest tests/unit/test_jsonb_sanitizer.py tests/integration/test_jsonb_nan_persistence.py -v
# Expected: assertion failures (the regression catches the revert).
git stash pop
.venv/bin/pytest tests/unit/test_jsonb_sanitizer.py tests/integration/test_jsonb_nan_persistence.py -v
# Expected: green again.
```

This sanity check satisfies SC-003.

---

## 4. Optional Postgres-fixture stretch test

The CI suite uses SQLite for speed. To run the integration test against a real Postgres (production-faithful), use the existing compose Postgres:

```bash
cd agent
DATABASE_URL='postgresql+psycopg://agent:agent@localhost:5432/agent' \
  .venv/bin/pytest tests/integration/test_jsonb_nan_persistence.py -v
```

This requires the compose Postgres to be running. Optional — not gated by SC.

---

## 5. What to inspect during PR review

- `agent/src/discogs_agent/persistence/sanitize.py` (new) — confirm the function is pure, recursive, and uses only stdlib (`math.isnan`, `math.isinf`).
- `agent/src/discogs_agent/persistence/models.py` — confirm the `_SanitizedJSON` `TypeDecorator` wraps the existing `JSONB().with_variant(JSON(), "sqlite")` chain and that `JSONType = _SanitizedJSON` is exported. The five existing column declarations (lines that say `JSONType` in their `mapped_column(...)` call) MUST be unchanged.
- `agent/tests/unit/test_jsonb_sanitizer.py` (new) — 6 named cases per research §R2.
- `agent/tests/integration/test_jsonb_nan_persistence.py` (new) — verify it writes a NaN through `ToolCallRepo.create`, flushes, expires, fetches, and asserts `None` not `NaN`.
- `specs/004-agent-v1/contracts/postgres-schema.md` — confirm §7 landed verbatim from `contracts/amendment-004-postgres-schema.md`.

Per SC-006, the sanitizer should be imported at exactly **one** place in `agent/src/discogs_agent/persistence/`. Verify with:

```bash
grep -rn "sanitize_for_jsonb\|from .sanitize\|from discogs_agent.persistence.sanitize" \
  agent/src/discogs_agent/persistence/
```

Expected: exactly one import in `models.py`. Anything else is a discipline violation.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Post-fix the bug still reproduces | Image not rebuilt after the code change | `docker compose up --build agent-api` |
| Regression test fails on a clean checkout | `JSONType` import path drift, or someone removed the `TypeDecorator` | Inspect `models.py` for the `_SanitizedJSON` class. Diff against the amendment's "Implementation pointer". |
| Integration test fails with `BadStatementError` or similar SQLAlchemy error | The `TypeDecorator`'s `cache_ok` flag was not set | Confirm `cache_ok = True` per research §R1. |
| Sanitizer breaks an existing test by mutating a clean dict | Sanitizer not respecting FR-005 (must not mutate) | Audit the recursion: every `dict` / `list` branch must construct a new container, not append to the input. |
