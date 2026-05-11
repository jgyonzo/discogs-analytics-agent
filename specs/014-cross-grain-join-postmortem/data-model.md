# Data Model: 014-cross-grain-join-postmortem

**Date**: 2026-05-10
**Scope**: this feature is *taxonomic*, not data-shaped. No new database tables, columns, or persisted entities. The artifacts that change are (a) rendered prose in the schema-context block, (b) runtime values flowing through existing JSON columns, (c) a new in-process constant in the safety checker. This document enumerates each artifact and its before/after shape — read it as a glossary of state shapes, not a database schema.

---

## Entity 1: Cross-grain traversal hint text

**Location**: `agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph` function, lines 224–246 (the "Cross-grain traversal hints" sub-block).

**Type**: list of strings, appended to the rendering output. Rendered into the `{schema_context_block}` substring of every code-generation and repair prompt. Stored verbatim in `agent_tool_calls.input_json` for the `dataset_schema_reader` row.

**Pre-014 content** (current, from the deployed renderer and the golden):

```
Cross-grain traversal hints:
- master_id and release_id are DIFFERENT identifier namespaces. They cannot be compared to each other.
- To go from master_fact to artists or labels, traverse a release-grain table:
    master_fact -> release_unique_view (on master_id) -> release_artist_bridge (on release_id)
- Prefer release_unique_view (one row per release) over release_fact for cross-grain joins; release_fact is row-multiplied by style and may inflate counts.
- Bridges are NOT unique on release_id — one row per (release × artist) in release_artist_bridge, one row per (release × label) in release_label_bridge.
```

**Post-014 content**: see `research.md §R3` for the exact replacement.

**Invariant**: the text MUST appear byte-equivalent in two locations:

1. `agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph` (deployed source of truth).
2. `agent/tests/integration/golden/schema_context_block.txt` (regenerated golden — locks the deployed text).

Mirrored normative description lives in `specs/005-agent-schema-context/contracts/schema-context.md` (cross-grain hints section). Mirror is prose, not byte-equivalent — describes the MUST clauses rather than the verbatim text.

---

## Entity 2: Forbidden-joins list (rendered prose)

**Location**: `agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph` function, lines 251–260 (the "Forbidden joins" sub-block, conditional on `has_master_fact = True`).

**Type**: list of strings, appended to the rendering output. Same delivery surface as Entity 1.

**Pre-014 content** (current — unchanged by 014):

```
Forbidden joins (will return semantically wrong rows even if the SQL runs):
- master_fact.master_id  =  release_artist_bridge.release_id
- master_fact.master_id  =  release_label_bridge.release_id
- master_fact.main_release_id  =  release_*_bridge.release_id  (use the master_id traversal instead unless you specifically want only the primary release of the master)
```

**Post-014 content**: identical to pre-014. **Entity 2's text is not modified by 014** — only Entity 1 (the cross-grain hint) changes. The forbidden-joins list keeps its current wording; 014 promotes it to runtime enforcement via Entity 3 below.

**Invariant**: the rendered text and the runtime constant (Entity 3) MUST match in their pair-list contents. Sync is enforced by code review + the contract document. Programmatic parity check is acknowledged in research.md §R10 as future hardening, not load-bearing for 014.

---

## Entity 3: `_FORBIDDEN_JOIN_PAIRS` — new safety-checker constant

**Location**: `agent/src/discogs_agent/tools/sql_safety_checker.py` (module-level constant, new in 014).

**Type**: `tuple[tuple[str, str, str, str], ...]` — tuple of 4-tuples, each tuple is `(left_table, left_column, right_table, right_column)`.

**Initial value** (matches the rendered list in Entity 2):

```python
_FORBIDDEN_JOIN_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("master_fact", "master_id", "release_artist_bridge", "release_id"),
    ("master_fact", "master_id", "release_label_bridge", "release_id"),
    ("master_fact", "main_release_id", "release_artist_bridge", "release_id"),
    ("master_fact", "main_release_id", "release_label_bridge", "release_id"),
)
```

**Symmetry**: predicate is symmetric. The scanner MUST check both orientations (`A.x = B.y` and `B.y = A.x`) for each pair.

**Conditionality**: the rule is conditional on `has_master_fact = True` in the schema context (matches Entity 2's conditional rendering).

**Mutation policy**: adding a new pair is a contract amendment to `004/contracts/sql-safety.md`. The pre-existing rule names (`"ddl_dml"`, `"read_only_required"`, `"forbidden_table"`, `"sql_invalid"`) follow the same policy.

---

## Entity 4: `SafetyViolation.rule` — new value `"forbidden_join"`

**Location**: `agent/src/discogs_agent/tools/sql_safety_checker.py` (existing `SafetyViolation` dataclass).

**Type**: existing field, shape unchanged.

**Pre-014 value set**:

| Value | Meaning |
|-------|---------|
| `"ddl_dml"` | First-token check failed (INSERT/UPDATE/DELETE/etc.). |
| `"forbidden_function"` | Generated SQL references read_csv / read_parquet / glob / S3 / HTTP / etc. |
| `"read_only_required"` | Generated Python didn't pass `read_only=True` to `duckdb.connect`. |
| `"sql_invalid"` | DuckDB `EXPLAIN` rejected the SQL (syntax / type / binder error). |
| `"forbidden_table"` | SQL references a non-allowlisted table or one absent from the runtime snapshot. |

**Post-014 value set additions**:

| Value | Meaning |
|-------|---------|
| `"forbidden_join"` | **NEW (014)**. SQL contains a join predicate matching a pair in `_FORBIDDEN_JOIN_PAIRS` (after alias resolution + comment stripping). Conditional on `has_master_fact = True`. |

**Detail string format**: `"{table_a}.{col_a} = {table_b}.{col_b}"` with unqualified table names. For `main_release_id` pairs, append the legitimate-sometimes hint. See research.md §R5 for exact formats per pair.

---

## Entity 5: Alias map (in-memory, per-validation)

**Location**: ephemeral — constructed inside `_scan_forbidden_joins` per validation call.

**Type**: `dict[str, str]` mapping `alias` → `underlying_table_name`. Bare-table references (no alias) self-map.

**Construction**: scan the SQL for `FROM <table> [AS] <alias>` and `JOIN <table> [AS] <alias>` patterns. Use sqlparse-tokenized SQL after comment stripping.

**Lifetime**: discarded after the predicate scan completes. Not persisted; not exposed in any output.

**Why this is an entity worth naming**: it's the load-bearing primitive that lets the regex predicate-scanner handle aliased references (`mf.master_id` → `master_fact.master_id`). Without it, the regex would only match fully-qualified references, missing the trigger case.

---

## Entity 6: Renumbered ETL pointer document

**Location**: `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` (pre-014) → `successor-015-pointer.md` (post-014).

**Type**: Markdown document. Filename + content change; no runtime impact.

**Filename invariant**: the filename MUST match the referenced spec number. Pre-013, `014-release-unique-view-materialization` was the provisional ETL spec name. Post-014, that spec name bumps to `015-...` because 014 is now occupied by this spec.

**Content change**: every occurrence of `014-release-unique-view-materialization` (provisional ETL spec name) → `015-release-unique-view-materialization`. Plus a new historical-context note at the top of the file (see research.md §R8).

---

## What is explicitly NOT a data-model entity in 014

For clarity:

- **No new database tables** — Postgres is untouched.
- **No new columns** — `agent_runs`, `agent_tool_calls`, `agent_model_usage` shapes are unchanged.
- **No new DuckDB tables/views** — the published DuckDB contract is untouched. The ETL-side rewrite of `release_unique_view` (now tracked by `015-release-unique-view-materialization` provisionally) remains deferred.
- **No new LangGraph state keys** — `AgentState` is unchanged.
- **No new prompt placeholders** — `{schema_context_block}`, `{failure_details}`, etc. are reused as-is.
- **No taxonomy change to the `SafetyOutput` schema** — the new rule flows through the existing `violations: list[SafetyViolation]` field.

---

## Validation rules from spec requirements

| Spec FR | Validation rule | Entity affected |
|---------|----------------|-----------------|
| FR-001 to FR-005 | Cross-grain hint text contains `release_fact` (not `release_unique_view`) as the traversal table; contains "NOT a usable traversal surface"; preserves namespaces-different line; preserves bridge-cardinality line | Entity 1 |
| FR-006 | Two byte-equivalence locations for Entity 1 (schema.py source + golden) | Entity 1 |
| FR-008 | New `_scan_forbidden_joins` pass exists in sql_safety_checker | Entity 3 + Entity 5 |
| FR-009 | `_FORBIDDEN_JOIN_PAIRS` contains exactly the 4 initial entries | Entity 3 |
| FR-010 | Aliases resolved before pattern matching | Entity 5 |
| FR-011 | Violation rule is exactly `"forbidden_join"`; detail in canonical unqualified-table form | Entity 4 |
| FR-012 | Rule conditional on `has_master_fact = True` | Entity 3 + Entity 4 |
| FR-018 | Renamed pointer file exists at the new path; old path does not | Entity 6 |

---

## State transitions

The only "state transition" relevant to this feature is the lifecycle of a single agent run when the LLM hallucinates a forbidden join:

```text
code_generator emits SQL with `mf.master_id = rab.release_id` →
  sql_safety_checker runs →
    Pass 0/1/2 succeed (SQL is syntactically valid; tables are allowlisted) →
    _scan_forbidden_tables succeeds →
    _scan_forbidden_joins (NEW in 014):
      strip comments →
      build alias map: {mf: master_fact, rab: release_artist_bridge} →
      scan ON predicates →
      resolve mf.master_id → master_fact.master_id →
      resolve rab.release_id → release_artist_bridge.release_id →
      match against _FORBIDDEN_JOIN_PAIRS →
      emit SafetyViolation(rule="forbidden_join", detail="master_fact.master_id = release_artist_bridge.release_id") →
  SafetyOutput(allowed=False, violations=[<the new violation>]) →
agent retry path engages:
  retry_count incremented →
  code_generator re-runs with `{failure_details}` containing "Safety violation: forbidden_join: master_fact.master_id = release_artist_bridge.release_id" →
  LLM regenerates with the correct release_fact traversal →
sql_safety_checker passes →
sandbox_executor runs →
chart_validator passes →
agent_runs.status = "succeeded"
```

No other state transitions are introduced or modified by 014.
