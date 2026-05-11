# Quickstart: verify 014-cross-grain-join-postmortem

**Audience**: developer or reviewer validating that the 014 implementation lands correctly.
**Pre-requisites for live steps**: agent component is running locally via `docker-compose up agent-api postgres`; published DuckDB is mounted; OpenAI key is set in `.env`.

Verification procedure, not a development guide. Each step is grep-or-curl-checkable.

---

## Step 1 — New unit tests pass

```sh
cd agent
uv run pytest tests/unit/test_sql_safety_checker.py -v
```

Expected: all pre-014 cases pass + 6 new cases per research.md §R7 (one will be `SKIPPED` for the CTE-indirection known gap; the rest PASS).

Specifically verify these new test cases by name:

```sh
uv run pytest tests/unit/test_sql_safety_checker.py -v -k "forbidden_join"
```

Expected: at least 6 tests collected, at least 5 passing, 1 skipped (CTE-indirection gap, intentional).

---

## Step 2 — Updated test_schema_context.py assertions pass

```sh
cd agent
uv run pytest tests/unit/test_schema_context.py -v -k "join_graph"
```

Expected: all `test_join_graph_*` tests pass. The pre-014 phrase assertion on `"master_fact -> release_unique_view"` has been replaced with `"master_fact -> release_fact (on master_id)"`; the new positive-prohibition assertion (`"release_unique_view is NOT a usable traversal surface"`) is in place.

---

## Step 3 — Integration golden in sync

```sh
cd agent
uv run pytest tests/integration/test_schema_context_join_graph.py -v
```

Expected: all four tests pass (including `test_rendered_block_matches_golden`).

Verify the new wording is in the golden + the renderer:

```sh
grep -c "master_fact -> release_fact (on master_id)" \
  agent/src/discogs_agent/duckdb_layer/schema.py \
  agent/tests/integration/golden/schema_context_block.txt
```

Expected: `1` and `1` (one occurrence in each file).

Verify the old contradicting line is GONE:

```sh
grep -c "Prefer release_unique_view" \
  agent/src/discogs_agent/duckdb_layer/schema.py \
  agent/tests/integration/golden/schema_context_block.txt
```

Expected: `0` and `0` (the legacy line is removed from both).

Verify the positive prohibition is present:

```sh
grep -c "release_unique_view is NOT a usable traversal surface" \
  agent/src/discogs_agent/duckdb_layer/schema.py \
  agent/tests/integration/golden/schema_context_block.txt
```

Expected: `1` and `1`.

---

## Step 4 — Forbidden-joins list still present (regression guard for 009's contribution)

```sh
grep -c "master_fact.master_id  =  release_artist_bridge.release_id" \
  agent/src/discogs_agent/duckdb_layer/schema.py \
  agent/tests/integration/golden/schema_context_block.txt
```

Expected: `1` and `1`. The forbidden-joins section (009's contribution) is unchanged by 014; it MUST still appear verbatim in both files.

---

## Step 5 — Renumbered ETL pointer is in place

```sh
# OLD path no longer exists
test ! -f specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md && \
  echo "OK: successor-014-pointer.md removed"

# NEW path exists
test -f specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md && \
  echo "OK: successor-015-pointer.md present"

# Content references 015 (not 014) for the ETL spec name
grep -c "015-release-unique-view-materialization" \
  specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md

# Historical-context note present
grep -c "originally drafted as.*successor-014-pointer.md" \
  specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md
```

Expected: all four checks succeed. The 015 count is at least 2 (title + provisional naming section). The historical-context note count is exactly 1.

---

## Step 6 — Upstream contract amendments are applied

```sh
# 005/schema-context.md no longer mentions "Prefer release_unique_view"
grep -c "Prefer release_unique_view" \
  specs/005-agent-schema-context/contracts/schema-context.md

# Should be 0 after FR-015 lands

# 005/schema-context.md mentions the new release_fact traversal
grep -c "master_fact -> release_fact (on master_id)" \
  specs/005-agent-schema-context/contracts/schema-context.md

# Should be at least 1

# 004/sql-safety.md has the new §2.4 / §3.2.4 sections
grep -c "Forbidden cross-grain joins\|Forbidden-join scan" \
  specs/004-agent-v1/contracts/sql-safety.md

# Should be at least 2
```

Expected: 0, ≥1, ≥2.

---

## Step 7 — Full agent test suite passes (no regressions)

```sh
cd agent
uv run pytest tests/unit tests/integration -q
```

Expected: at least `148 passed, 2 skipped` (pre-014 baseline was 143 passed; 014 adds at least 5 new unit tests, 1 of which is skipped intentionally → net 148+).

Pre-014 baseline (per 013's recorded post-implementation count): 143 passed, 2 skipped.

---

## Step 8 — Live-infra: replay the triggering question (SC-001)

Requires `docker-compose up agent-api postgres` and an OpenAI key.

```sh
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{
    "user_query": "top 5 artists with works having the most versions, excluding Various and Unknown Artist"
  }' | jq '{status, generated_sql}'
```

Expected:

- `status: "succeeded"` (NOT `failed_validation`).
- `generated_sql` contains `JOIN release_artist_bridge ... ON release_fact.release_id = release_artist_bridge.release_id` (or an equivalent shape with aliases).
- `generated_sql` does NOT contain `master_fact.master_id = release_artist_bridge.release_id` or `release_unique_view` in a JOIN.

Verify:

```sh
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"user_query":"top 5 artists with works having the most versions, excluding Various and Unknown Artist"}' \
  | jq -r '.generated_sql' \
  | grep -E "master_fact\.master_id\s*=\s*release_\w+_bridge\.release_id"
```

Expected: no output (the forbidden join is not generated).

---

## Step 9 — Live-infra: probe the safety checker directly (SC-004)

If a developer-mode endpoint exists, post the exact SQL from run `2557c2ce-...` directly to the safety checker. Otherwise, inspect a triggered run's `agent_tool_calls` row.

```sh
# Inspect the most recent sql_safety_checker call that fired forbidden_join
docker exec -i postgres psql -U agent -d agent -c \
  "SELECT input_json -> 'generated_code',
          jsonb_path_query_first(output_json, '\$.violations[*] ? (@.rule == \"forbidden_join\")')
   FROM agent_tool_calls
   WHERE node_name = 'sql_safety_checker'
     AND output_json @> '{\"allowed\": false}'
   ORDER BY created_at DESC LIMIT 1;"
```

Expected: at least one such row exists post-014, showing the violation rule `forbidden_join` with a detail string of the form `"master_fact.<id_col> = release_<bridge>_bridge.release_id"`.

---

## Step 10 — Live-infra: five-question regression probe (SC-002)

```sh
for q in \
  "top 5 artists with works having the most versions, excluding Various and Unknown Artist" \
  "top labels by master-count for Pink Floyd" \
  "which artists have at least 10 distinct works" \
  "which works by Depeche Mode have the most versions" \
  "show me artists with the most masters released in the 1990s"; do
  echo "=== $q ==="
  curl -s -X POST http://localhost:8001/query \
    -H "Content-Type: application/json" \
    -d "{\"user_query\":$(jq -Rn --arg q "$q" '$q')}" \
    | jq '{status, has_forbidden_join: (.generated_sql | tostring | test("master_fact\\.\\w+\\s*=\\s*release_\\w+_bridge"))}'
done
```

Expected for each: `status: "succeeded"` and `has_forbidden_join: false`.

---

## Step 11 — Live-infra: curated demo regression check (SC-003)

Re-run the seven curated questions from `008/contracts/curated-questions.md` per `013/quickstart.md §Step 7`. All MUST return `succeeded` (or `succeeded_empty` if appropriate). None should hit the new `forbidden_join` rule (the curated set doesn't generate cross-grain joins, but the regression check is a safety net).

---

## Step 12 — Constitution + checklist re-validation

```sh
cat specs/014-cross-grain-join-postmortem/checklists/requirements.md
```

All items should remain `[x]`. If any drifted to `[ ]` during implementation (e.g., a new clarification surfaced), update the spec and the checklist before merge.

---

## Roll-back

If 014 needs to be reverted post-merge:

- Revert the four code files: `schema.py` (`_render_join_graph` lines 224–246), `sql_safety_checker.py` (new constant + new function + new pipeline call), `test_schema_context.py` (phrase-assertion updates), `test_sql_safety_checker.py` (6 new test cases — delete).
- Revert the golden: `tests/integration/golden/schema_context_block.txt`.
- Revert the three upstream contract amendments (005 cross-grain hint, 009 supersession, 004 sql-safety §2.4 + §3.2.4 + §4 row).
- Re-rename `successor-015-pointer.md` → `successor-014-pointer.md` and revert the content edits.

Roll-back surface is moderate (~10 file reverts) but self-contained. No database migrations, no infra changes.
