# Amendment to `004/contracts/sql-safety.md` — new `forbidden_join` rule

**Source feature**: `014-cross-grain-join-postmortem`
**Target file**: `specs/004-agent-v1/contracts/sql-safety.md`
**Insert location**: a new sub-section `§2.4 Forbidden cross-grain joins` immediately after `§2.3 Forbidden function patterns` (current 004 line ~118). A new pass `§3.2.4 Forbidden-join scan` immediately after `§3.2.3 CTE-alias detection`.
**Predecessor**: 004-agent-v1 (defined the baseline rule taxonomy + the two-pass check structure).

This amendment promotes the forbidden-joins list (introduced as descriptive prose in 009-schema-context-join-graph) to runtime enforcement at the `sql_safety_checker` boundary. The rendered list in the schema-context block (009's contribution) is unchanged; this amendment adds the runtime rule that statically rejects SQL containing those join predicates.

---

## New §2.4: Forbidden cross-grain joins

Insert after §2.3 (Forbidden function patterns), as a peer sub-section under §2 (Forbidden).

```markdown
### 2.4 Forbidden cross-grain joins

*Added 2026-05-10 by `014-cross-grain-join-postmortem`. Promotes the
forbidden-joins list from descriptive prose in the rendered schema-
context block (009-schema-context-join-graph contribution) to runtime
enforcement at the `sql_safety_checker` boundary. Named incident: run
`2557c2ce-21e2-4838-8790-d54528e8043c` ("top 5 artists with works
having the most versions, excluding 'Various' and 'Unknown Artist'")
on 2026-05-10.*

When the LLM generates SQL containing a join predicate of the form
`<table_a>.<col_a> = <table_b>.<col_b>` where the resolved (table, column)
pair matches a forbidden cross-grain pair, the safety checker MUST emit
a `SafetyViolation(rule="forbidden_join", detail=<canonical predicate>)`
and reject with `allowed=False`.

#### Forbidden cross-grain join pairs (initial set)

| Left side | Right side | Severity |
|---|---|---|
| `master_fact.master_id` | `release_artist_bridge.release_id` | hard-reject |
| `master_fact.master_id` | `release_label_bridge.release_id` | hard-reject |
| `master_fact.main_release_id` | `release_artist_bridge.release_id` | hard-reject |
| `master_fact.main_release_id` | `release_label_bridge.release_id` | hard-reject |

The list MUST match `_FORBIDDEN_JOIN_PAIRS` in
`agent/src/discogs_agent/tools/sql_safety_checker.py` and the rendered
text emitted by `agent/src/discogs_agent/duckdb_layer/schema.py`
`_render_join_graph` "Forbidden joins" sub-block. Adding a new pair is
a contract amendment to this document.

#### Conditionality

The forbidden-join rule MUST be conditional on `has_master_fact = True`
in the schema context. When `has_master_fact = False`, the rule is
skipped (matches the renderer's conditional emission of the forbidden-
joins sub-block).

#### Detail string format

The `detail` field of the emitted `SafetyViolation` MUST use unqualified
table names (not aliases). For `main_release_id` pairs, the detail
SHOULD include the legitimate-sometimes hint inline. Examples:

- `"master_fact.master_id = release_artist_bridge.release_id"`
- `"master_fact.main_release_id = release_artist_bridge.release_id (use the master_id traversal instead unless you specifically need the primary release of each master)"`

#### Why it matters

These joins are semantically wrong but mechanically valid (both columns
are `BIGINT`). DuckDB will execute the SQL and return rows driven by
coincidental ID overlaps between unrelated entities. The result is a
silent wrong answer the user has no way to detect without external
verification. The runtime rule catches the hallucination at safety-check
time, surfaces a named violation in the run record, and forces the
agent's retry path to engage.

#### Known coverage gap

The implementation strategy (research.md §R1) uses a regex-based scan
over the cleaned SQL plus an alias resolver. SQL that hides the
forbidden join inside a CTE (e.g.,
`WITH t AS (SELECT master_id FROM master_fact) SELECT ... FROM t JOIN
release_artist_bridge ON t.master_id = release_artist_bridge.release_id`)
will NOT be caught — the scanner sees `t.master_id` but cannot resolve
`t` back to `master_fact`. The prompt-side fix (009 hint update, this
spec's US1) remains the primary mitigation for this case. A future AST-
based upgrade is acknowledged but deferred.
```

---

## New §3.2.4: Forbidden-join scan

Insert after §3.2.3 (CTE-alias detection), as a peer pass under §3.2 (Pass 2 — DuckDB EXPLAIN).

```markdown
#### 3.2.4 Forbidden-join scan (regex on cleaned SQL)

*Added 2026-05-10 by `014-cross-grain-join-postmortem`.*

After the forbidden-table re-scan (§3.2.2) succeeds AND `has_master_fact
= True` in the schema context, the safety checker MUST run a three-stage
forbidden-join scan over the extracted SQL:

1. **Strip SQL comments** using `sqlparse.format(sql, strip_comments=True)`.
   Defends against false positives where the SQL legitimately mentions a
   forbidden join pair in a comment (e.g., documentation).

2. **Build the alias map** by scanning `FROM <table> [AS] <alias>` and
   `JOIN <table> [AS] <alias>` patterns in the cleaned SQL. Map each
   alias to its underlying table name; bare-table references self-map.

3. **Scan ON predicates** for patterns of the form `<ref_a> = <ref_b>`
   where each ref is `<alias_or_table>.<column>`. For each match,
   resolve aliases via the map, then check the resolved pair against
   `_FORBIDDEN_JOIN_PAIRS`. Both orientations are checked (predicate is
   symmetric). On match, emit `SafetyViolation(rule="forbidden_join",
   detail=<canonical predicate>)` and reject with `allowed=False`.

The scan MUST be a no-op when `has_master_fact = False` (matches the
renderer's conditional emission of the forbidden-joins sub-block).

The forbidden-join scan does NOT bypass the rest of the safety pipeline;
violations are emitted alongside any other violations from earlier
passes.
```

---

## Updated §4: Returning the verdict (additive — new rule value)

The §4 "Returning the verdict" rule-name table (around 004/sql-safety.md line 331) needs one new row:

```markdown
| Rule name | When emitted | Where in the pipeline |
|---|---|---|
| ... (existing rows preserved) ... |
| `forbidden_join` | SQL contains a join predicate matching a pair in `_FORBIDDEN_JOIN_PAIRS` (after alias resolution + comment stripping). Conditional on `has_master_fact = True`. | §3.2.4 |
```

Existing rule names (`ddl_dml`, `forbidden_function`, `read_only_required`, `sql_invalid`, `forbidden_table`) are unchanged.

---

## Updated §6: Testing (additive — new test-case requirements)

Add to §6's test-case enumeration (around 004/sql-safety.md line 372):

```markdown
- The exact SQL from run `2557c2ce-...` (with aliases `mf`, `rab`) MUST
  produce a single `SafetyViolation(rule="forbidden_join", detail=
  "master_fact.master_id = release_artist_bridge.release_id")`.
- The label-bridge variant (`master_fact.master_id =
  release_label_bridge.release_id`, fully qualified) MUST produce the
  same `forbidden_join` rule.
- A `main_release_id` variant MUST produce the rule with the
  legitimate-sometimes hint in the detail string.
- A legitimate `release_fact.release_id = release_artist_bridge.release_id`
  join MUST NOT trigger the rule (regression guard).
- A CTE-indirected forbidden join MUST NOT trigger the rule (documents
  the known coverage gap; the test is `pytest.mark.skip`-annotated with
  the reason).
- A `has_master_fact = False` schema context with a master_fact reference
  in the SQL MUST NOT trigger `forbidden_join` (the forbidden-table rule
  fires first; verify the conditional).
```

---

## Implementation pointer

Implementation lands as part of 014:

- `agent/src/discogs_agent/tools/sql_safety_checker.py` — adds:
  - Module-level constant `_FORBIDDEN_JOIN_PAIRS: tuple[tuple[str, str, str, str], ...]` with the 4 initial pairs.
  - Helper function `_strip_comments(sql: str) -> str` using sqlparse.
  - Helper function `_build_alias_map(sql: str) -> dict[str, str]`.
  - Main scan function `_scan_forbidden_joins(sql: str, has_master_fact: bool) -> list[SafetyViolation]`.
  - Call to `_scan_forbidden_joins` in the main checker pipeline, after `_scan_forbidden_tables` and before the success return.
- `agent/tests/unit/test_sql_safety_checker.py` — adds 6 new test cases per research.md §R7.
- `specs/004-agent-v1/contracts/sql-safety.md` — receives the §2.4, §3.2.4, §4 table row, and §6 test-case additions per this amendment.
