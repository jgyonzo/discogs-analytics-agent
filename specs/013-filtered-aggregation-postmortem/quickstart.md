# Quickstart: verify 013-filtered-aggregation-postmortem

**Audience**: developer or reviewer validating that the 013 implementation lands correctly.
**Pre-requisites**: agent component is running locally via `docker-compose up agent-api postgres`; published DuckDB is mounted at `/app/data/published/duckdb/discogs.duckdb`; OpenAI key is set in `.env`.

This document is a verification procedure, not a development guide. Each step is grep-or-curl-checkable.

---

## Step 1 — Unit tests pass

After implementation:

```sh
cd agent
uv run pytest tests/unit/test_sandbox_signal_mapping.py tests/unit/test_chart_validator_oom_rule.py -v
```

Expected: all 7 test cases pass (5 for the runner per `sandbox-exception-taxonomy.md §Unit-test coverage`, 2 for the validator per `research.md §R8`).

---

## Step 2 — Integration golden is in sync

```sh
cd agent
uv run pytest tests/integration/test_rendered_block_matches_golden.py -v
```

Expected: passes. The `_DOMAIN_GLOSSARY` entry #3 in `duckdb_layer/schema.py` and the golden at `tests/integration/golden/schema_context_block.txt` are byte-equivalent.

Verify the new wording is in the glossary:

```sh
grep -n "in any JOIN or GROUP BY" agent/src/discogs_agent/duckdb_layer/schema.py
grep -n "in any JOIN or GROUP BY" agent/tests/integration/golden/schema_context_block.txt
```

Both MUST return a hit. (Pre-013 wording "for catalog-wide aggregations" MUST NOT appear in either file.)

---

## Step 3 — Glossary mirror in code_generator.md and repair_code.md

```sh
grep -n "in any JOIN or GROUP BY" agent/src/discogs_agent/prompts/code_generator.md
grep -n "in any JOIN or GROUP BY" agent/src/discogs_agent/prompts/repair_code.md
```

Both MUST return a hit. The wording is paraphrased shorter than the glossary entry but contains the load-bearing clause.

---

## Step 4 — Q1 description updated (FR-011)

```sh
grep -n "release_unique_view" specs/008-agent-frontend-v1/contracts/curated-questions.md
```

The Q1 section (around lines 13–22) MUST NOT contain `release_unique_view`. The replacement description should mention `COUNT(DISTINCT release_id)` + `release_fact`. Other Q sections (Q2–Q7) MAY still mention `release_unique_view` if they had it pre-013; 013 only changes Q1.

---

## Step 5 — Replay the failing Depeche Mode question end-to-end (SC-002)

```sh
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{
    "user_query": "what is the work of Depeche Mode that has more versions?"
  }' | jq '{status, final_response, generated_sql}'
```

Expected:

- `status: "succeeded"` (NOT `failed_validation`).
- `final_response` is a sentence naming a real Depeche Mode work and its version count.
- `generated_sql` contains `release_fact` and either `release_artist_bridge` or a `master_fact.release_count` shortcut; MUST NOT contain `JOIN release_unique_view` or `GROUP BY` after `FROM release_unique_view`.

```sh
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"user_query":"what is the work of Depeche Mode that has more versions?"}' \
  | jq -r '.generated_sql' \
  | grep -E 'release_unique_view'
```

Expected: no output (the SQL no longer references the view).

---

## Step 6 — Verify the OOM observability path with a deliberately-large query (SC-001, SC-005, SC-006)

Construct a probe question that the LLM cannot avoid OOM-ing. Easiest reliable trigger: bypass the agent and send raw SQL through a developer-mode endpoint, OR construct a question that forces the LLM into a known-pathological shape despite the prompt steering.

If no such endpoint exists, use a one-off Python harness:

```sh
docker exec agent-api python -c "
import duckdb
con = duckdb.connect('/app/data/published/duckdb/discogs.duckdb', read_only=True,
                     config={'temp_directory': '/tmp/duckdb', 'memory_limit': '1GB'})
# Materialize the view fully — guaranteed OOM
con.execute('SELECT * FROM release_unique_view').df()
"
```

That call SHOULD OOM the container. To observe the named cause through the agent path, fall back to an inducing question that lands the LLM in the view-OOM path even with the new glossary (a question with explicit instructions like *'use release_unique_view and group by genre'*; the prompt's rule-of-thumb is steering, not a hard prohibition, so a sufficiently explicit user demand will still produce the OOM path).

Inspect the resulting agent_runs row:

```sh
docker exec -i postgres psql -U agent -d agent -c \
  "SELECT status, jsonb_path_query_first(metadata, '\$.errors[*]') FROM agent_runs ORDER BY started_at DESC LIMIT 1;"
```

Expected: `metadata.errors[]` contains a rule with `oom_killed`.

Inspect the `agent_tool_calls` row for the sandbox executor:

```sh
docker exec -i postgres psql -U agent -d agent -c \
  "SELECT output_json -> 'exception_type', output_json -> 'exception_message'
   FROM agent_tool_calls
   WHERE node_name = 'sandbox_executor'
   ORDER BY created_at DESC LIMIT 1;"
```

Expected: `exception_type = "oom_killed"` (NOT `"nonzero_exit"`), `exception_message` contains `"cgroup OOM-killer"` or `"exceeded memory budget"`.

Inspect the `final_response`:

```sh
docker exec -i postgres psql -U agent -d agent -c \
  "SELECT final_response FROM agent_runs ORDER BY started_at DESC LIMIT 1;"
```

Expected: the string contains one of `memory`, `too heavy`, `narrow your question`, `reduce scope` (SC-006).

---

## Step 7 — Curated demo regression check (SC-004)

Run each of the seven curated questions from `008/contracts/curated-questions.md`:

```sh
for q in \
  "Show releases by decade as a bar chart" \
  "Compare Vinyl and CD releases by decade" \
  "Top 15 countries by number of releases" \
  "Trend of Techno releases by decade" \
  "Top 10 labels by release count" \
  "Distribution of primary genres in the 2010s" \
  "Show me 5 random releases with their year, country, and format"; do
  echo "=== $q ==="
  curl -s -X POST http://localhost:8001/query \
    -H "Content-Type: application/json" \
    -d "{\"user_query\":$(jq -Rn --arg q "$q" '$q')}" \
    | jq '.status'
done
```

Expected: all seven return `"succeeded"` (or `"succeeded_empty"` if the curated set legitimately produces no rows for any). None should return `failed_validation`.

---

## Step 8 — Five-question single-artist version-spread check (SC-003)

```sh
for q in \
  "what is the work of Depeche Mode that has the most versions?" \
  "how many versions of Pink Floyd's Dark Side of the Moon exist?" \
  "which Beatles album has the most release versions?" \
  "which Daft Punk work has the most versions?" \
  "show me Aphex Twin releases with the most versions"; do
  echo "=== $q ==="
  curl -s -X POST http://localhost:8001/query \
    -H "Content-Type: application/json" \
    -d "{\"user_query\":$(jq -Rn --arg q "$q" '$q')}" \
    | jq '{status, sql_has_view: (.generated_sql | tostring | test("release_unique_view"))}'
done
```

Expected for each: `status: "succeeded"` and `sql_has_view: false`.

If any returns `sql_has_view: true`, inspect the SQL — it MUST be a spot-check (`FROM release_unique_view WHERE release_id = N`) and NOT a JOIN or GROUP BY usage. If it's a JOIN/GROUP BY, the glossary tightening has not bitten and FR-006 needs revisiting.

---

## Step 9 — Contract documents in place

```sh
ls specs/013-filtered-aggregation-postmortem/contracts/
```

Expected: four files —

- `amendment-004-code-generation.md`
- `amendment-005-schema-context.md`
- `sandbox-exception-taxonomy.md`
- `successor-014-pointer.md`

```sh
grep -l "oom_killed" specs/013-filtered-aggregation-postmortem/contracts/*.md
```

Expected: at least three of the four files. (The `successor-014-pointer.md` doesn't necessarily mention `oom_killed`; the other three should.)

---

## Step 10 — Constitution Check is satisfied

Re-read `specs/013-filtered-aggregation-postmortem/plan.md` "Constitution Check" table. Each row marked ✅ MUST still be defensible after looking at the implemented code. The two nuance rows (Principle V surface-narrowing, VII.a taxonomy literals) are not violations and need no further action.

---

## Step 11 — Spec-quality checklist re-validated

```sh
cat specs/013-filtered-aggregation-postmortem/checklists/requirements.md
```

All items should be `[x]`. If any drifted to `[ ]` during implementation (e.g., new clarifications surfaced), the spec needs an update before merge.

---

## Roll-back

If 013 needs to be reverted post-merge:

- Revert the three code files: `sandbox/runner.py`, `tools/chart_validator.py`, `graph/nodes/response_synthesizer.py`.
- Revert the three prompt/text files: `duckdb_layer/schema.py` (`_DOMAIN_GLOSSARY`), `prompts/code_generator.md`, `prompts/repair_code.md`.
- Revert the golden: `tests/integration/golden/schema_context_block.txt`.
- Revert the Q1 description line in `008/contracts/curated-questions.md`.
- Delete the two new test modules.

Roll-back surface is small and self-contained. No database migrations, no infra changes.
