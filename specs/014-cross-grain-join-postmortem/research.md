# Research: 014-cross-grain-join-postmortem

**Date**: 2026-05-10
**Purpose**: Resolve the implementation choices the spec deliberately left open and pin the exact wording / regex / data-structure shapes the contracts and tasks need.

The spec's "Edge Cases" section flagged two implementation choices to be resolved here (regex vs. AST; strict-vs-soft for `main_release_id`). This research nails those and adds the wording + test-coverage decisions that fall out of them.

---

## R1. Implementation strategy for the forbidden-join scanner

**Decision**: Regex-based pre-scan over the extracted SQL, plus a sqlparse-driven alias resolver. NOT a full AST parse. NOT sqlglot.

**Three-stage algorithm**:

1. **Strip SQL comments** (single-line `--` and block `/* */`) — defends against the comment-false-positive edge case the spec flagged.
2. **Build the alias map** by scanning `FROM <table> [AS] <alias>` and `JOIN <table> [AS] <alias>` patterns. Map alias → underlying table name. Bare-table references (no alias) map themselves.
3. **Scan ON predicates** with a tight regex matching `<left_ref>\s*=\s*<right_ref>` where each ref is `<alias_or_table>.<column>`. For each match, resolve aliases via the map, then check the resolved `(table_a.col_a, table_b.col_b)` pair against the forbidden-pair set. Both orientations checked (predicate is symmetric).

**Rationale**:

- The triggering case (`mf.master_id = rab.release_id`) is the dominant shape. The Explore agent confirmed the existing checker uses sqlparse-tokenization + regex-on-raw-SQL for every other rule (ddl_dml scan, forbidden-tables scan, forbidden-functions scan). The new rule fits the same pattern with minimal new code.
- sqlglot would add a heavyweight dependency (~MB-class) for a single new rule. Rejected on dependency-footprint grounds.
- A full sqlparse AST traversal of join predicates is possible but more brittle than regex against the cleaned text (sqlparse's grouping rules around `JOIN ... ON ...` are notoriously inconsistent across versions). Rejected on maintainability grounds.
- The CTE-indirection gap is real but bounded — the spec acknowledges it explicitly in Edge Cases (and the prompt-side fix in US1 is the primary mitigation). A future AST upgrade is one possible follow-on; not load-bearing for 014.

**Alternatives considered**:

- *sqlglot AST*: rejected — new heavyweight dep, overkill for the bug class.
- *DuckDB EXPLAIN-plan text scan*: rejected — EXPLAIN already runs in Pass 2; its plan text doesn't preserve table aliases in a uniformly greppable way (it normalizes to internal names), so alias→table mapping is lost.
- *Pure regex on raw SQL without alias resolution*: rejected — the trigger case uses aliases, so a pattern that only matches `master_fact.master_id` would miss `mf.master_id`. Alias resolution is non-negotiable.

---

## R2. Strict-vs-soft handling of `master_fact.main_release_id` joins

**Decision**: Strict — same `forbidden_join` rule fires for `master_fact.main_release_id = release_*_bridge.release_id`. The detail string carries an extra note pointing the LLM at the master_id traversal.

**Rationale**:

- The rendered list already includes `main_release_id` as a forbidden cross-grain join. Promoting the rendered list verbatim to runtime enforcement keeps the rendered-block-as-canonical-source-of-truth principle intact.
- The "sometimes legitimate" case (the operator genuinely wants only the primary release of the master) is rare in agent traffic. Operator override on demand is explicitly out of scope per the spec.
- Soft-reject (warning-only) would create taxonomy debt: now we have a "violation severity" axis that nothing else uses, and the response synthesizer would need new dispatch logic. Not worth the complexity for a rare case.
- The detail string can still inform the LLM. Suggested format: `"master_fact.main_release_id = release_artist_bridge.release_id (use the master_id traversal instead unless you specifically need the primary release of each master)"`.

**Alternatives considered**:

- *Soft-reject (rule fires with severity="warn")*: rejected — new severity axis is overkill; one rare false-positive doesn't justify it.
- *Skip the `main_release_id` patterns entirely; rely on the rendered guidance*: rejected — that's a partial enforcement that contradicts what the rendered block declares. If we enforce only some of the rendered patterns, the rendered list becomes misleading documentation.
- *Make it operator-configurable*: rejected — out of scope per the spec.

---

## R3. Exact new wording for the cross-grain traversal hint

**Decision**: Replace `_render_join_graph` lines 224–246 with the following. The "namespaces are different" line is preserved. The traversal worked-example uses `release_fact`. The legacy "Prefer release_unique_view" line is removed entirely. A new explicit cross-reference note replaces it.

```python
    # Cross-grain traversal hints sub-block.
    lines.append("Cross-grain traversal hints:")
    if has_master_fact:
        lines.append(
            "- master_id and release_id are DIFFERENT identifier namespaces. "
            "They cannot be compared to each other."
        )
        lines.append(
            "- To go from master_fact to artists or labels, traverse via release_fact:"
        )
        lines.append(
            "    master_fact -> release_fact (on master_id) "
            "-> release_artist_bridge (on release_id)"
        )
        lines.append(
            "    Use COUNT(DISTINCT release_fact.master_id) for 'works per X' "
            "and COUNT(DISTINCT release_fact.release_id) for 'releases per X'. "
            "release_fact has grain release × style, so naive COUNT(*) double-counts."
        )
    lines.append(
        "- release_unique_view is NOT a usable traversal surface — it's only safe "
        "for single-release spot-checks (see glossary entry #3). Always traverse "
        "through release_fact for cross-grain joins."
    )
    lines.append(
        "- Bridges are NOT unique on release_id — one row per (release × "
        "artist) in release_artist_bridge, one row per (release × label) in "
        "release_label_bridge."
    )
    lines.append("")
```

**Three deltas from the pre-014 wording**:

1. Worked example: `master_fact -> release_unique_view (on master_id) -> release_artist_bridge (on release_id)` → `master_fact -> release_fact (on master_id) -> release_artist_bridge (on release_id)`.
2. New COUNT-pattern note added immediately under the worked example. Tells the LLM both `master_id` and `release_id` `COUNT(DISTINCT)` patterns and warns about the release × style multiplication.
3. The line `"Prefer release_unique_view ... over release_fact for cross-grain joins; release_fact is row-multiplied by style and may inflate counts"` is **deleted**. It is replaced by: `"release_unique_view is NOT a usable traversal surface — it's only safe for single-release spot-checks (see glossary entry #3). Always traverse through release_fact for cross-grain joins."`

**Why explicit, not implicit**: 013's experience taught us that the LLM resolves contradictions by inventing shortcuts. Saying *"release_unique_view is NOT a usable traversal surface"* (positive prohibition) + cross-reference is stronger than just removing the recommendation. Tells the LLM both what to do and what NOT to do.

**Alternatives considered**:

- *Just remove the contradicting line, no replacement*: rejected — the LLM may revert to release_unique_view by default if not actively steered away. The positive prohibition is the necessary counterweight.
- *Recommend `master_fact.release_count` as the answer to "works per artist"*: rejected for this hint — `master_fact.release_count` is a pre-aggregated count per master, which is what 013's spec mentioned as one of two valid answers for the Depeche Mode case. But for the broader "top artists by works" question, you need to GROUP BY artist, which means you still need to traverse to the bridge. The release_count shortcut is question-specific; the hint should be question-shape-agnostic.

---

## R4. Forbidden-pair data structure in the safety checker

**Decision**: Module-level constant in `sql_safety_checker.py`, a tuple of `(left_table, left_column, right_table, right_column)` 4-tuples. The same data lives in the canonical contract document `contracts/amendment-004-sql-safety.md`; adding a new pair requires updating both.

```python
# Forbidden cross-grain join pairs. Each entry is (left_table, left_col,
# right_table, right_col). The pair is symmetric (predicate is symmetric);
# the scanner checks both orientations. Matches the rendered list in
# `schema.py:_render_join_graph` "Forbidden joins" sub-block.
#
# Adding a pair is a contract amendment — see
# specs/014-cross-grain-join-postmortem/contracts/amendment-004-sql-safety.md.
_FORBIDDEN_JOIN_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("master_fact", "master_id", "release_artist_bridge", "release_id"),
    ("master_fact", "master_id", "release_label_bridge", "release_id"),
    ("master_fact", "main_release_id", "release_artist_bridge", "release_id"),
    ("master_fact", "main_release_id", "release_label_bridge", "release_id"),
)
```

**Rationale**:

- 4-tuple (table, col, table, col) is greppable and one-line-per-entry. Same shape as the rendered list.
- Tuple of tuples (immutable) signals taxonomy-constant intent.
- Symmetry: the scanner checks both `A.x = B.y` and `B.y = A.x` forms. Simpler than declaring 8 pairs.
- "Add a pair = contract amendment" matches the pattern 013 established for `exception_type` taxonomy literals.

**Alternatives considered**:

- *Frozenset of `frozenset({(table, col), (table, col)})` to encode symmetry*: rejected — frozen sets of frozen sets are read-only-friendly but cryptic in source. The tuple-of-tuples + explicit both-orientations check is clearer.
- *Single canonical orientation enforced at insertion time*: rejected — error-prone for future maintainers who add pairs.

---

## R5. Detail string format for the `forbidden_join` rule

**Decision**: Canonical detail string is `"{table_a}.{col_a} = {table_b}.{col_b}"` using unqualified table names (not aliases). For the `main_release_id` cases, append the legitimate-sometimes hint inline.

Examples:

| Triggering SQL fragment | Resolved detail string |
|---|---|
| `JOIN release_artist_bridge rab ON mf.master_id = rab.release_id` (with `mf = master_fact`) | `"master_fact.master_id = release_artist_bridge.release_id"` |
| `JOIN release_label_bridge rlb ON mf.master_id = rlb.release_id` | `"master_fact.master_id = release_label_bridge.release_id"` |
| `JOIN release_artist_bridge rab ON mf.main_release_id = rab.release_id` | `"master_fact.main_release_id = release_artist_bridge.release_id (use the master_id traversal instead unless you specifically need the primary release of each master)"` |

**Rationale**:

- Greppable across logs / dashboards / tests. An operator filtering `agent_tool_calls.output_json` for `"forbidden_join"` violations can group by detail string and see the dominant variant.
- Unqualified names (not aliases): aliases are query-local and noisy. The contract canonical form is the table.column form.
- The `main_release_id` hint surfaces *why* the rule fired even on the rarely-legitimate case. The LLM sees this in the repair prompt's `{failure_details}` slot (per 013's plumbing).

**Alternatives considered**:

- *Include the aliases in the detail*: rejected — alias names are query-local; canonical form is more useful for aggregation.
- *Detail is just the table-pair (no column)*: rejected — drops information; harder for the LLM to fix on retry.
- *Detail is structured JSON*: rejected — `SafetyViolation.detail` is a `str` per existing contract; not changing the shape just for this rule.

---

## R6. SQL comment stripping (defends the false-positive edge case)

**Decision**: Strip comments before scanning. Use sqlparse's `format()` with `strip_comments=True`. Apply this preprocessing to the SQL string before both the alias-map build and the predicate scan.

```python
import sqlparse
cleaned = sqlparse.format(extracted_sql, strip_comments=True)
```

**Rationale**:

- The spec's Edge Cases section flagged this: if the generated SQL contains a comment like `-- master_fact.master_id = release_artist_bridge.release_id (forbidden)`, a naive regex would false-positive.
- sqlparse is already a dependency; `format(strip_comments=True)` is documented and battle-tested.

**Alternatives considered**:

- *Regex-strip comments*: rejected — comment syntax has edge cases (nested `/* */`, strings containing `--`); sqlparse handles them correctly.
- *Skip comment stripping; accept false positives*: rejected — could break a curated demo question if its SQL happens to comment about a forbidden join. Cheap to fix; do it.

---

## R7. Test-case matrix for the new rule (FR-014)

**Decision**: 6 test cases in `tests/unit/test_sql_safety_checker.py`, plus 2 regression-guard test cases in `tests/unit/test_schema_context.py` for FR-007.

### `test_sql_safety_checker.py` — 6 new cases:

| # | Case | Expected outcome |
|---|------|------------------|
| 1 | The exact SQL from run `2557c2ce-...` (with aliases `mf`, `rab`) | `allowed=False`; one violation `rule="forbidden_join"`, detail contains `"master_fact.master_id = release_artist_bridge.release_id"`. |
| 2 | Label-bridge variant (`master_fact.master_id = release_label_bridge.release_id`, fully qualified) | `allowed=False`; one `forbidden_join` violation; detail names label-bridge. |
| 3 | `main_release_id` variant (with aliases) | `allowed=False`; one `forbidden_join` violation; detail includes the legitimate-sometimes hint. |
| 4 | Legitimate `release_fact.release_id = release_artist_bridge.release_id` join (regression guard) | `allowed=True`; no `forbidden_join` violation. |
| 5 | Forbidden predicate inside a CTE-indirected query (documents the known gap) | The rule does NOT fire — gap is intentional. The test asserts no `forbidden_join` violation AND uses `pytest.mark.skip(reason="known regex-scanner gap; tracked in 014/research.md §R1")` so it's visible in `pytest -v` output. |
| 6 | `has_master_fact = False` schema context with SQL containing fake `master_fact.master_id = release_artist_bridge.release_id` text (which would have hit Pass 2's forbidden-table check first) | The `forbidden_join` rule is conditional on `has_master_fact`; verify it does NOT fire when master_fact is absent. (In practice the master_fact reference would fail the forbidden-table check first, so this test exercises the conditional explicitly.) |

### `test_schema_context.py` — 2 regression-guard updates:

| # | Case | Update needed |
|---|------|---------------|
| A | The pre-014 phrase assertion `"master_fact -> release_unique_view (on master_id)"` (around line 179–180) | Replace with the new phrase: `"master_fact -> release_fact (on master_id)"`. |
| B | The pre-014 phrase assertion that `"Prefer release_unique_view"` appears in the cross-grain section | Replace with a new assertion that the cross-grain section contains `"release_unique_view is NOT a usable traversal surface"` (positive prohibition). |

The existing assertion that the forbidden-joins lines are present (`"master_fact.master_id  =  release_artist_bridge.release_id"`) is unchanged and remains the load-bearing regression guard for the rendered block.

**Rationale**: 6 + 2 cases cover the trigger case, both variants, the regression guards, the known gap, and the conditional rendering. Sufficient for SC-001 through SC-005 to be verifiable at the unit level.

---

## R8. Renumbering 013's pointer doc — exact content edits

**Decision**: Two-step file operation:

1. `git mv specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md`
2. In the renamed file, replace every occurrence of `014-release-unique-view-materialization` with `015-release-unique-view-materialization`. Update the document title and the "Provisional naming and timing" section's spec-number line.

After the rename:

- Document title: `# Successor pointer: future ETL-component spec (\`015-release-unique-view-materialization\`)`
- Provisional naming section: `Spec number: \`015-release-unique-view-materialization\` (provisional; ...)`
- Add a one-line note at the top of the file: *"Originally drafted as `successor-014-pointer.md` during 013's planning; renumbered to 015 by 014-cross-grain-join-postmortem (FR-018) because 014 was taken by the cross-grain hint fix."*

**Rationale**:

- `git mv` (not `rm + add`) preserves the file's history under git blame.
- Content updates keep the doc internally consistent.
- The historical-context note at the top tells future readers the document's provenance without forcing them to spelunk through commit history.

**Alternatives considered**:

- *Don't rename the file; add a note pointing readers at 015 for the actual spec number*: rejected — filename should match the referenced spec number for greppability. Same logic as 013's choice to name the pointer `successor-014-pointer.md` in the first place.
- *Renumber in 014's contracts/ instead of 013's*: rejected — the pointer originally belonged to 013's deferral. Moving it across directories breaks the "this spec's contracts/ directory is its own self-contained record" pattern.

---

## R9. Verification path for the deployed change (links to quickstart.md)

The quickstart.md (Phase 1 deliverable) will exercise:

1. Unit tests (T-equivalent for FR-014, FR-007 — pass without live infra).
2. Integration golden test (`test_rendered_block_matches_golden` — pass without live infra).
3. Grep checks (the new wording present; the old contradiction phrase absent — pass without live infra).
4. Live replay of the triggering question (`top 5 artists ... excluding Various ... ` — requires live agent).
5. Live probe of the safety checker with the run `2557c2ce-...` SQL (requires running agent).
6. The 7 curated demo questions still pass (regression check; requires live agent).

Steps 4–6 are deferred to operator-side execution (mirrors 013's quickstart pattern). Steps 1–3 are fully verifiable in CI.

---

## R10. Forbidden-pair data also lives in the rendered block — do we need a third copy?

**Decision**: NO additional canonical data store. The forbidden-pair list is canonical in two places:

1. **Rendered block source** at `agent/src/discogs_agent/duckdb_layer/schema.py` lines 251–260 (the `_render_join_graph` `if has_master_fact:` branch).
2. **Safety-checker constant** at `agent/src/discogs_agent/tools/sql_safety_checker.py` (`_FORBIDDEN_JOIN_PAIRS`, new in 014).

Both are normatively pinned in `contracts/amendment-004-sql-safety.md` (the contract document).

The two source-code locations are kept in sync by code review + the contract document's enumeration. A unit test could enforce parity programmatically; that's a future hardening but not load-bearing for 014.

**Rationale**:

- Adding a third "single source of truth" file would create more sync points, not fewer. The renderer and the checker each have their own responsibilities (display vs. enforce); duplicating the list across both is correct.
- A programmatic parity test (`assert _FORBIDDEN_JOIN_PAIRS matches the rendered list`) is appealing but premature — the list is 4 entries and stable. If it grows past ~8 entries, that's the trigger to add the test.

**Alternatives considered**:

- *Single canonical YAML/TOML file imported by both*: rejected — single source point but adds a new file format to the agent's dep graph. Not worth it for 4 entries.
- *Renderer reads from the safety-checker constant*: rejected — creates an awkward import dependency (`duckdb_layer` → `tools`) that crosses architectural boundaries the codebase otherwise respects.

---

## R11. Open questions surfaced during research — NONE

All design questions from the spec are resolved above. No `[NEEDS CLARIFICATION]` markers remain.

---

## Summary of file edits the implementation will perform

For `tasks.md` (next phase) to enumerate:

| File | Change | FR(s) |
|------|--------|-------|
| `agent/src/discogs_agent/duckdb_layer/schema.py` | Replace `_render_join_graph` lines 224–246 (cross-grain traversal hints sub-block) with R3 wording. Lines 198–222 + 249–262 unchanged. | FR-001 through FR-005 |
| `agent/src/discogs_agent/tools/sql_safety_checker.py` | Add `_FORBIDDEN_JOIN_PAIRS` constant + `_scan_forbidden_joins(sql, has_master_fact)` function; call it after `_scan_forbidden_tables` in the main checker. Use sqlparse comment-stripping + alias resolution. | FR-008 through FR-012 |
| `agent/tests/integration/golden/schema_context_block.txt` | Regenerate via `UPDATE_GOLDEN=1 pytest tests/integration/test_schema_context_join_graph.py`. | FR-006 |
| `agent/tests/unit/test_schema_context.py` | Update 2 phrase assertions per R7 table B. | FR-007 |
| `agent/tests/unit/test_sql_safety_checker.py` | Add 6 new test cases per R7 table A. | FR-014 |
| `specs/005-agent-schema-context/contracts/schema-context.md` | Cross-grain hint section — third-round rewrite. | FR-015 |
| `specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md` | Add supersession note for the hint section (the forbidden-joins section unchanged). | FR-016 |
| `specs/004-agent-v1/contracts/sql-safety.md` | Add `forbidden_join` rule sub-section. | FR-017 |
| `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` | `git mv` to `successor-015-pointer.md` + content edits per R8. | FR-018 |
| `specs/014-cross-grain-join-postmortem/contracts/*` | Write 4 new contract documents (Phase 1 deliverable). | n/a (contract authoring) |

10 distinct file edits + 1 rename + 4 new contract documents in this feature's directory.
