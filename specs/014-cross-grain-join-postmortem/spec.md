# Feature Specification: Cross-grain join postmortem — 009 hint update + static forbidden-join enforcement

**Feature Branch**: `014-cross-grain-join-postmortem`
**Created**: 2026-05-10
**Status**: Draft
**Input**: User direction: *"Option B with a new specify"* — full SDD back-fill of the diagnosis already shared in conversation for run `2557c2ce-21e2-4838-8790-d54528e8043c`.

## Context: a 013-induced regression of 009's safety net

On 2026-05-10 (shortly after 013 merged), run `2557c2ce-21e2-4838-8790-d54528e8043c` generated this SQL for the question *"top 5 artists with the most-versioned works, excluding 'Various' and 'Unknown Artist'"*:

```sql
WITH artist_master_count AS (
    SELECT rab.artist_name,
           COUNT(DISTINCT mf.master_id) AS work_version_count
    FROM master_fact mf
    JOIN release_artist_bridge rab ON mf.master_id = rab.release_id      -- ← FORBIDDEN
    WHERE rab.artist_name NOT IN ('Various', 'Unknown Artist')
    GROUP BY rab.artist_name
)
SELECT artist_name, work_version_count
FROM artist_master_count
ORDER BY work_version_count DESC LIMIT 5
```

The join predicate `mf.master_id = rab.release_id` is **literally the first entry in 009's "Forbidden joins" anti-pattern list**. `master_id` and `release_id` are different identifier namespaces — they cannot be compared. DuckDB accepted the join because both are `BIGINT`, the SQL ran to completion, and the result is a meaningless top-5 driven by coincidental ID overlaps between unrelated entities.

This is the silent-wrong-answer bug class **009 was specifically built to prevent** by rendering the forbidden-join anti-patterns into the LLM-facing schema-context block. The anti-pattern WAS rendered. The LLM ignored it.

### Why the LLM ignored the rendered anti-pattern

Look at what 009 still says vs. what 013 newly tightened, both rendered in the same schema-context block today (post-013 merge):

**009's cross-grain traversal hint (current):**

```
- To go from master_fact to artists or labels, traverse a release-grain table:
    master_fact -> release_unique_view (on master_id) -> release_artist_bridge (on release_id)
- Prefer release_unique_view (one row per release) over release_fact for cross-grain joins;
  release_fact is row-multiplied by style and may inflate counts.
```

**013's glossary entry #3 (current, post-013):**

```
DO NOT use release_unique_view in any JOIN or GROUP BY, regardless of WHERE filters …
release_unique_view is ONLY safe for spot-check queries that filter directly on a single
release literal (e.g., SELECT * FROM release_unique_view WHERE release_id = N).
```

These are **directly contradictory** for the master→artist/label question class:

- 009 says: traverse via `release_unique_view`.
- 013 says: never use `release_unique_view` in any JOIN.

The LLM read both, recognized the contradiction, and resolved it the worst possible way — by punting on both and inventing the shortcut (the forbidden join `master_fact.master_id = release_artist_bridge.release_id`, which both 009 and the rendered block explicitly forbid).

This is a 013-induced regression. Pre-013, 009's hint was internally consistent (use the view, JOIN is fine). Post-013, 009's recommended path is forbidden, but 009's hint text was not updated.

### What 013's planning should have caught

`013/research.md §R10` ("Edge-case validation") checked all seven curated demo questions and confirmed none of them does the master→artist traversal at full-catalog scale. The check missed two things:

1. **Non-curated traffic does master→artist all the time.** *"Top artists by works"*, *"which works by Depeche Mode have most versions"*, etc. are the question class 009 was built for — and 009's cross-grain hint was load-bearing for it.
2. **R10 didn't audit 009's hint text against 013's new glossary.** If it had, the contradiction would have been visible in the post-013 rendered block, and 013 would have updated 009's hint in the same change.

013's spec.md US2 acceptance scenario 1 actually anticipated the *correct* SQL shape:

> the generated SQL counts versions via `release_fact` + `release_artist_bridge` (or directly via `master_fact.release_count` joined to the artist-bridge semi-join), with no `release_unique_view` appearing in a JOIN or GROUP BY.

— but 013 described the desired behavior without ever updating the prompt artifact (the cross-grain hint) that would actually steer the LLM there for the broader question class.

### What 014 closes

Two work items, complementary:

1. **Cross-grain hint update (US1)** — resolves the 013-induced contradiction at its source. 009's hint now recommends `release_fact` as the master → release-grain traversal table. The conflicting `release_unique_view` recommendation is removed; the glossary entry #3 prohibition stays intact. Both pieces of LLM-facing guidance now agree.
2. **Static forbidden-join enforcement (US2)** — defense-in-depth at the safety-checker layer. The forbidden-joins list is already canonical data in the rendered block; promoting it to enforcement at `sql_safety_checker` means the next prompt-steering gap of this class becomes a *loud* retry instead of a *silent* wrong answer.

These two stories are independent but complementary. US1 is the prompt-side fix (closes the specific regression); US2 is the runtime safety net (closes the bug class regardless of prompt contents).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Cross-grain hint and glossary stop contradicting each other (Priority: P1) 🎯 MVP

The rendered schema-context block's cross-grain traversal hint no longer recommends a path that the glossary entry #3 forbids. After this story lands, the LLM reading the block gets **one** internally-consistent recommended path for master → release-grain traversal: `master_fact → release_fact (on master_id) → release_artist_bridge (on release_id)`. The `release_unique_view` recommendation is removed from the cross-grain hint; the glossary's prohibition on the view in JOIN/GROUP BY stays in force.

**Why this priority**: this directly closes the reported regression (`2557c2ce-...`). It's a wording fix in one renderer function plus a golden regeneration — minimal surface area, immediate effect on LLM behavior. Without it, the same question class will keep producing forbidden-join SQL on every run.

**Independent Test**: re-run the question *"top 5 artists with works having the most versions, excluding 'Various' and 'Unknown Artist'"* through the post-014 agent. Inspect `agent_runs.generated_sql`: the SQL MUST use `release_fact` as the master → bridge traversal table, and MUST NOT contain any predicate of the shape `master_fact.<id_col> = release_*_bridge.<id_col>`. Inspect the rendered schema-context block emitted on any run: the cross-grain hint MUST recommend `release_fact` (not `release_unique_view`) and MUST explicitly note that `release_unique_view` is NOT a usable traversal surface.

**Acceptance Scenarios**:

1. **Given** the master→artist question above, **When** the agent runs end-to-end on post-014 code, **Then** the generated SQL contains `JOIN release_artist_bridge ... ON release_fact.release_id = release_artist_bridge.release_id` (or an equivalent shape) and does NOT contain `master_fact.master_id = release_artist_bridge.release_id` or `release_unique_view` in a JOIN.
2. **Given** the rendered schema-context block emitted on any run, **When** the operator inspects the "Cross-grain traversal hints" section, **Then** the recommended traversal path uses `release_fact` (not `release_unique_view`), and a clarifying note states that `release_unique_view` is NOT a usable traversal surface (cross-referencing glossary entry #3).
3. **Given** the rendered schema-context block, **When** the operator inspects glossary entry #3, **Then** its prohibition on `release_unique_view` in JOIN/GROUP BY (from 013) is unchanged. The two sections now agree.
4. **Given** a single-master spot-check question (e.g., *"show me master_id 12345"*), **When** the agent runs, **Then** `release_unique_view WHERE release_id = N` is still permitted — the 013 carve-out is intact and unaffected by this story.

---

### User Story 2 — Forbidden-join hallucinations are caught at the safety check (Priority: P2)

The `sql_safety_checker` promotes the rendered forbidden-joins list from descriptive prose to a static enforcement rule. When the LLM generates SQL containing a forbidden cross-grain join predicate (e.g., `master_fact.master_id = release_artist_bridge.release_id`, with or without table aliases), the safety checker rejects with `rule="forbidden_join"`. The agent's existing retry path engages; the LLM regenerates with the named violation in the repair prompt's `{failure_details}` slot.

**Why this priority**: US1 alone closes the specific regression but leaves the bug class open. New question shapes that 014 didn't anticipate (e.g., a future LLM regression on a recursive CTE that smuggles `master_id` into a bridge join) would silently produce wrong answers again. US2 makes any future instance of the same bug class **loud** — caught at safety-check time, surfaced in the run record as a named violation, retried, and either fixed or visibly failed.

P2 (not P1) because US1 alone is sufficient to close the *reported* bug; US2 is the durable safety net. P2-ranked also because the regex-based predicate parser has known coverage gaps (CTE-indirection, see Edge Cases) that the spec acknowledges rather than papering over.

**Independent Test**: Pass the exact SQL from run `2557c2ce-...` directly into the `sql_safety_checker` (via unit test or integration probe). MUST return `allowed=False` with `violations` containing `{"rule": "forbidden_join", "detail": "master_fact.master_id = release_artist_bridge.release_id"}` (or equivalent — exact detail string is implementation choice). Verify the same for the label-bridge variant and the `main_release_id` variant. Verify a legitimate join (`release_fact.release_id = release_artist_bridge.release_id`) still passes.

**Acceptance Scenarios**:

1. **Given** the forbidden cross-grain SQL from run `2557c2ce-...` (with table aliases `mf`, `rab`), **When** `sql_safety_checker` runs on it, **Then** the output contains `allowed=False` and a violation with `rule="forbidden_join"`.
2. **Given** SQL with `master_fact.master_id = release_label_bridge.release_id` (the label-side variant), **When** `sql_safety_checker` runs, **Then** the same `rule="forbidden_join"` violation fires.
3. **Given** SQL with the legitimate `release_fact.release_id = release_artist_bridge.release_id` (correct release-grain join), **When** `sql_safety_checker` runs, **Then** no `forbidden_join` violation fires.
4. **Given** SQL that hallucinates a forbidden join, **When** the agent's repair path engages (retry_count incremented), **Then** the repair prompt's `{failure_details}` slot contains the named rule (`forbidden_join`) and the detail string, so the LLM can act on it.
5. **Given** a master-fact-absent schema context (the conditional case where 009 omits the join graph entirely), **When** the safety checker runs, **Then** the forbidden-join rule does NOT fire (the list is conditional on `has_master_fact`, matching the renderer's behavior).

---

### Edge Cases

- **Table aliases in predicates**: the triggering case used aliases (`mf` for `master_fact`, `rab` for `release_artist_bridge`). The regex-based predicate parser must either resolve aliases or accept that alias-vs-fully-qualified-name is an implementation detail. US2's regex MUST handle the common case where the FROM/JOIN clause introduces an alias and the ON predicate uses that alias. Fully-qualified references (`master_fact.master_id`) MUST also be caught.
- **CTE-indirection** (known gap, documented): if the LLM hides the forbidden join inside a CTE (e.g., `WITH t AS (SELECT master_id FROM master_fact) SELECT ... FROM t JOIN release_artist_bridge ON t.master_id = release_artist_bridge.release_id`), the regex-based parser will not catch the cross-grain violation. Static enforcement is best-effort; the prompt steering (US1) is the primary mitigation. The spec ACKNOWLEDGES this gap explicitly rather than papering over it. Future work could promote the rule to an AST-based parser (e.g., `sqlglot`); deferred.
- **`master_fact.main_release_id` is a release_id**: per the contract, `main_release_id` IS a `release_id`, and joining it against a bridge's `release_id` is *not* mechanically wrong — it just returns ONLY the primary release of each master, which is rarely what the user means. The current rendered anti-pattern says *"use the master_id traversal instead unless you specifically want only the primary release of the master"*. **For US2**: the forbidden-join rule MUST treat `main_release_id` as a soft-reject (still emits `rule="forbidden_join"` but with a hint in the detail that this case is sometimes legitimate). Or, alternative: keep the strict block on the two `master_id = release_id` pairs and leave `main_release_id` as renderer-only guidance. The spec leaves this as an implementation choice — both are defensible.
- **The hint update must not regress 013**: 014 only changes the cross-grain hint section; the glossary entry #3 (013's load-bearing artifact) is untouched. The carve-out for `release_unique_view WHERE release_id = N` spot-checks remains.
- **Conditional rendering**: the join-graph section (cross-grain hints + forbidden joins) is only emitted when `has_master_fact = True` (`schema.py:198–262`). When master_fact is absent, the cross-grain bug class is structurally unreachable. US2's runtime rule MUST respect this conditional: a master-fact-absent schema context should NOT emit `forbidden_join` violations even if the SQL happens to mention non-existent identifier columns.
- **Multi-CTE chains**: queries with deep CTE nesting (e.g., `WITH t1 AS (...), t2 AS (...) SELECT ... FROM t2 JOIN ...`) should still have their final ON predicates scanned. The regex can flatten CTE boundaries as far as the predicate-extraction allows.
- **Comments in SQL**: if the generated SQL contains a comment that literally writes `master_fact.master_id = release_artist_bridge.release_id` (e.g., as documentation), the simple regex would false-positive. Strip SQL comments before scanning.

## Requirements *(mandatory)*

### Functional Requirements

**US1 — Cross-grain hint update**

- **FR-001**: `_render_join_graph` in `agent/src/discogs_agent/duckdb_layer/schema.py` (currently lines 198–262) MUST be updated so the cross-grain traversal hint recommends `release_fact` as the master → release-grain traversal table, NOT `release_unique_view`. The canonical worked example becomes:

  ```
  master_fact -> release_fact (on master_id) -> release_artist_bridge (on release_id)
  ```

- **FR-002**: The hint MUST include an explicit anti-pattern note stating that `release_unique_view` is NOT a usable traversal surface, cross-referencing glossary entry #3. Suggested wording:

  > release_unique_view is NOT a usable traversal surface — it's only safe for single-release spot-checks (see glossary entry #3).

- **FR-003**: The hint MUST include a count-pattern note: use `COUNT(DISTINCT release_fact.master_id)` for "works per X" and `COUNT(DISTINCT release_fact.release_id)` for "releases per X". `release_fact`'s grain is release × style, so naive `COUNT(*)` double-counts.

- **FR-004**: The legacy line "Prefer release_unique_view (one row per release) over release_fact for cross-grain joins" MUST be removed. It directly contradicts 013's glossary and is the proximate cause of the reported regression.

- **FR-005**: The forbidden-joins sub-block (currently lines 251–260 of `_render_join_graph`) MUST remain unchanged. It is independently load-bearing and 014's US2 promotes it to runtime enforcement; 014's US1 doesn't modify it.

- **FR-006**: The integration golden at `agent/tests/integration/golden/schema_context_block.txt` MUST be regenerated to reflect the new wording. Existing test `test_rendered_block_matches_golden` MUST pass post-regen.

- **FR-007**: Existing unit-test assertions in `agent/tests/unit/test_schema_context.py:test_join_graph_section_present_when_master_fact_true` that lock the OLD wording (e.g., asserts on `"master_fact -> release_unique_view"`) MUST be updated to match the new wording. Assertions on the namespaces-different line and the forbidden-joins lines are unaffected.

**US2 — Static forbidden-join enforcement**

- **FR-008**: `sql_safety_checker.py` MUST add a new pass that scans extracted SQL for forbidden-join predicates. The implementation MAY be regex-based on the raw SQL (smallest-diff per the Explore findings; sqlparse already a dependency). The implementation SHOULD strip SQL comments first.

- **FR-009**: The forbidden-join list lives as a constant in the checker module. The initial set, matching the rendered list:

  | Left side | Right side | Severity |
  |---|---|---|
  | `master_fact.master_id` | `release_artist_bridge.release_id` | hard-reject |
  | `master_fact.master_id` | `release_label_bridge.release_id` | hard-reject |
  | `master_fact.main_release_id` | `release_artist_bridge.release_id` | hard-reject (see Edge Case) |
  | `master_fact.main_release_id` | `release_label_bridge.release_id` | hard-reject (see Edge Case) |

  Adding a new forbidden pair is a contract amendment (mirrors the glossary's amendment process).

- **FR-010**: The rule MUST handle table aliases. Specifically, an alias introduced in FROM/JOIN (e.g., `master_fact mf`) and used in the ON predicate (`mf.master_id`) MUST be resolved to its underlying table name before pattern matching. Both fully-qualified references AND aliased references MUST trigger the rule.

- **FR-011**: When the rule fires, the checker MUST emit `SafetyViolation(rule="forbidden_join", detail=<full table.column = table.column string in canonical form>)` and set `allowed=False`. The detail string MUST use unqualified table names (not aliases) for greppability.

- **FR-012**: The forbidden-join check MUST be conditional on `has_master_fact = True`. When `has_master_fact = False`, the rule is skipped (matches the renderer's conditional emission).

- **FR-013**: The repair-prompt path MUST surface the new rule's name + detail string into the `{failure_details}` slot. Plumbing exists per 013's research finding (the validator and safety violations both flow through `_format_failures`); confirm and test.

- **FR-014**: New unit tests under `agent/tests/unit/test_sql_safety_checker.py` MUST cover: (a) the exact triggering case with aliases; (b) the label-bridge variant; (c) the `main_release_id` variants; (d) a legitimate `release_fact.release_id = release_artist_bridge.release_id` join (regression guard); (e) a CTE-indirection case where the rule does NOT fire (documenting the known gap).

**Contract amendments**

- **FR-015**: `specs/005-agent-schema-context/contracts/schema-context.md` cross-grain traversal hints normative section (lines 245–256) MUST be updated to reflect the new wording. The amendment lives in this feature's `contracts/amendment-005-schema-context.md`.

- **FR-016**: `specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md` MUST be cross-referenced as superseded for the cross-grain hint section (the forbidden-joins section remains authoritative from 009; only the cross-grain hint changes). The amendment lives in this feature's `contracts/amendment-009-cross-grain-hint.md`.

- **FR-017**: `specs/004-agent-v1/contracts/sql-safety.md` MUST gain a new sub-section documenting the `forbidden_join` rule (rule name, when it fires, detail format, conditional on `has_master_fact`). The amendment lives in this feature's `contracts/amendment-004-sql-safety.md`.

**Renumbering admin**

- **FR-018**: `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` MUST be renamed to `successor-015-pointer.md` and its content updated: every reference to `014-release-unique-view-materialization` (provisional ETL spec name) becomes `015-release-unique-view-materialization` (or whatever number the ETL spec lands on when actually opened). 014 is now occupied by this spec; the ETL follow-on bumps to 015.

### Key Entities

- **Cross-grain traversal hint text** (current code lines 224–246 of `schema.py`; current contract text 005/schema-context.md:245–256 and 009/amendment-005:43–48; golden lines 36–41). After 014: wording reshaped to recommend `release_fact` and forbid `release_unique_view`-as-traversal.
- **Forbidden-joins list** (current code lines 251–260 of `schema.py`; current contract text 005/schema-context.md:258–271 and 009/amendment-005:50–54; golden lines 43–46). After 014: identical wording in the rendered block AND promoted to runtime enforcement in `sql_safety_checker`.
- **`SafetyViolation`** (existing, `sql_safety_checker.py`). After 014: gains a new `rule` value `"forbidden_join"`. Existing rules unchanged.
- **`SafetyOutput.violations`** (existing). After 014: may contain new `forbidden_join` entries; downstream consumers (validator, response_synthesizer, repair-prompt assembler) already handle generic violation lists without code change.
- **Renumbered pointer file** (013's `successor-014-pointer.md` → `successor-015-pointer.md`). Filename and content change; the ETL follow-on remains deferred.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The triggering question — *"top 5 artists with works having the most versions, excluding 'Various' and 'Unknown Artist'"* — runs to a `succeeded` status on the post-014 agent, AND the persisted `agent_runs.generated_sql` contains NO predicate of the shape `master_fact.<id_col> = release_*_bridge.<id_col>`. Verifiable by replaying the question end-to-end.

- **SC-002**: For a manually constructed set of at least 5 master→artist or master→label cross-grain questions (the trigger case + 4 more, e.g., *"top labels by master-count for Pink Floyd"*, *"artists with at least 10 distinct works"*, etc.), generated SQL contains zero forbidden-join predicates AND zero `release_unique_view` references in JOIN/GROUP BY. Verifiable by inspecting `agent_runs.generated_sql` across runs.

- **SC-003**: The seven curated demo questions from `008/contracts/curated-questions.md` continue to pass on post-014 code (no regressions from US1's hint change or US2's new rule).

- **SC-004**: When the `sql_safety_checker` is fed the exact SQL from run `2557c2ce-...`, the output contains exactly one `SafetyViolation` with `rule="forbidden_join"` and `allowed=False`. Verifiable by unit test.

- **SC-005**: When the `sql_safety_checker` is fed a legitimate `release_fact.release_id = release_artist_bridge.release_id` join, no `forbidden_join` violation fires. Verifiable by unit test.

- **SC-006**: The rendered schema-context block (post-014) does NOT contain the string `"Prefer release_unique_view ... over release_fact for cross-grain joins"` (the contradicting line). Verifiable by `grep` against the regenerated golden and against the deployed renderer output.

- **SC-007**: The rendered schema-context block (post-014) DOES contain a string of the form `release_fact (on master_id)` in the cross-grain traversal hints section. Verifiable by `grep`.

- **SC-008**: `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` no longer exists; `successor-015-pointer.md` exists with corresponding content updates. Verifiable by `ls` + `grep`.

- **SC-009**: All pre-014 baseline tests (143 passed, 2 skipped post-013) continue to pass. New unit tests (US2) add at least 5 cases per FR-014. Total post-014: at least 148 passed, 2 skipped.

## Assumptions

- **`release_fact` is sufficient for master → release-grain traversal.** `release_fact.master_id` is populated for all releases that belong to a master (per ETL contract `001/contracts/duckdb-schema.md`). Filter `WHERE master_id IS NOT NULL` to drop non-master releases. `release_fact`'s grain is release × style, so `COUNT(DISTINCT release_id)` or `COUNT(DISTINCT master_id)` collapses the style multiplication. No release_unique_view needed.
- **Regex-based predicate scanning is sufficient for US2's coverage.** The triggering case is direct (no CTE indirection). Most LLM hallucinations of the forbidden join class will use the direct form. The CTE-indirection gap is acknowledged in Edge Cases and deferred to a possible future AST-based upgrade.
- **The four forbidden pairs in FR-009 are exhaustive for the current schema.** Adding a fifth (e.g., if a new bridge table lands) is a contract amendment, not a code-only change.
- **The 013-induced contradiction was the only such cross-section conflict.** Other glossary/hint pairs (e.g., the bridges cardinality note, the style-vs-genre rule) are independent and unaffected.
- **No constitution amendment required.** 014 stays inside Principle VII.b (rendered-block-only schema info) and VII.c (this is the symmetric enforcement analog — declare the rule's mechanics alongside its rendered statement).

## Out of Scope

- **AST-based predicate parsing** (e.g., switching from sqlparse to sqlglot or DuckDB's `EXPLAIN(format json)`). Regex on raw SQL is sufficient for the trigger case and the immediate bug class. AST upgrade is a future-spec concern if a real CTE-indirection regression appears.

- **The ETL-side rewrite of `release_unique_view`** (still deferred; tracked by the renumbered `successor-015-pointer.md`). 014 does not modify the view's definition or any ETL component file.

- **A complete audit of every 009 hint vs. every 013 glossary entry.** 014 fixes the specific contradiction triggered by run `2557c2ce-...`. A broader audit (e.g., "do any other hint/glossary pairs contradict?") is a defensible but separate concern. If the audit finds more issues, they get their own follow-on.

- **Bypassing the safety check on operator demand.** The `forbidden_join` rule is hard-rejected. An operator override flag (e.g., for legitimate `main_release_id` cases) is NOT in scope.

- **Refactoring 013's contracts.** The `amendment-005-schema-context.md` from 013 stays as written; 014 produces its own amendments to the same upstream contracts (a third round on 005, mirroring how 010 was a second round on 004's postgres-schema contract).

## Dependencies

- **`agent/src/discogs_agent/duckdb_layer/schema.py`** lines 198–262 (`_render_join_graph`) — surgical site for FR-001 through FR-005.
- **`agent/src/discogs_agent/tools/sql_safety_checker.py`** — surgical site for FR-008 through FR-013 (the new forbidden-join scan pass).
- **`agent/tests/integration/golden/schema_context_block.txt`** — regenerated per FR-006.
- **`agent/tests/unit/test_schema_context.py`** — assertion updates per FR-007.
- **`agent/tests/unit/test_sql_safety_checker.py`** — new test cases per FR-014.
- **`specs/005-agent-schema-context/contracts/schema-context.md`** — normative amendment per FR-015.
- **`specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md`** — superseded for the cross-grain hint section per FR-016.
- **`specs/004-agent-v1/contracts/sql-safety.md`** — extended with the new rule per FR-017.
- **`specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md`** — renamed to `successor-015-pointer.md` with content updates per FR-018.
- **Predecessors**:
  - 009 (introduced the cross-grain hint and the forbidden-joins list)
  - 013 (tightened glossary entry #3 and inadvertently created the contradiction)
- **Successor** (provisional): `015-release-unique-view-materialization` — the ETL-side rewrite of the view, previously pointed at as "014" by 013, now bumped to 015. Remains deferred; 014 does not deliver it.
- **No constitution amendment**: Principle VII.b's rendered-block-only mandate is honored (014 modifies the same rendered block 009 introduced). Principle VII.c's symmetric-mechanics mandate is honored (014 declares the forbidden-join rule's enforcement alongside its rendered statement).
