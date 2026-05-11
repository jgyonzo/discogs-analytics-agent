---

description: "Task list for 014-cross-grain-join-postmortem: 009 hint update + static forbidden-join enforcement"
---

# Tasks: Cross-grain join postmortem — 009 hint update + static forbidden-join enforcement

**Input**: Design documents from `/specs/014-cross-grain-join-postmortem/`
**Plan**: [plan.md](./plan.md)
**Spec**: [spec.md](./spec.md)
**Research**: [research.md](./research.md)
**Data model**: [data-model.md](./data-model.md)
**Contracts**: [contracts/amendment-005-schema-context.md](./contracts/amendment-005-schema-context.md), [contracts/amendment-009-cross-grain-hint.md](./contracts/amendment-009-cross-grain-hint.md), [contracts/amendment-004-sql-safety.md](./contracts/amendment-004-sql-safety.md), [contracts/renumbering-013-pointer.md](./contracts/renumbering-013-pointer.md)
**Quickstart**: [quickstart.md](./quickstart.md)

**Tests**: Tests ARE included — spec FR-007 requires updating two phrase assertions in `test_schema_context.py`; spec FR-014 requires 6 new test cases in `test_sql_safety_checker.py` per research.md §R7. Integration test coverage is provided by regenerating the existing schema-context golden.

**Organization**: Two user stories (US1=P1 closes the reported regression; US2=P2 adds defense-in-depth). They are independent (different files; no shared state) but US1 is the MVP — shippable alone. Polish phase exercises both via the quickstart procedure plus applies the three upstream contract amendments and performs the renumbering admin.

---

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 = cross-grain hint; US2 = forbidden-join enforcement)
- Setup, Foundational, and Polish phases have NO story label

## Path Conventions

This feature lives entirely within the `agent/` component (Constitution Principle VI). Paths are repo-relative; key surfaces:

- Production code: `agent/src/discogs_agent/{duckdb_layer,tools}/`
- Tests: `agent/tests/unit/` (assertions updated + new cases), `agent/tests/integration/golden/` (golden regenerated)
- Documentation: `specs/004-agent-v1/contracts/`, `specs/005-agent-schema-context/contracts/`, `specs/013-filtered-aggregation-postmortem/contracts/` (renumbered file), `specs/014-cross-grain-join-postmortem/contracts/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Ensure the branch is in a clean state and the 014 design artifacts are visible to the implementer.

- [X] T001 Verify branch is `014-cross-grain-join-postmortem` and working tree has only expected pending changes — run `git status` and `git branch --show-current`. The pending items should be the spec/plan/research/data-model/contracts/quickstart artifacts written during `/speckit-specify` and `/speckit-plan` (plus CLAUDE.md and .specify/feature.json updates). No source code under `agent/src/` should be modified at this point.
- [X] T002 Run the existing agent unit + integration test suite from a baseline checkout to confirm green-before-014 — `cd agent && uv run pytest tests/unit tests/integration -q`. Record the test count; the 014 implementation MUST land with the baseline + 6 new tests (one skipped), all passing.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Verify the four contract documents written during `/speckit-plan` are in place. No new code-side prerequisites.

**⚠️ CRITICAL**: No user story work should begin until this verification passes.

- [X] T003 Verify the four 014 contract documents exist and are non-empty — `ls -la specs/014-cross-grain-join-postmortem/contracts/` MUST list `amendment-004-sql-safety.md`, `amendment-005-schema-context.md`, `amendment-009-cross-grain-hint.md`, `renumbering-013-pointer.md`. Read each and confirm it matches the spec's FR-015 through FR-018 surfaces. If any is missing or stale, return to `/speckit-plan`.

**Checkpoint**: Foundation ready — US1 and US2 can now proceed in parallel.

---

## Phase 3: User Story 1 — Cross-grain hint update (Priority: P1) 🎯 MVP

**Goal**: The rendered schema-context block's cross-grain traversal hint no longer recommends `release_unique_view` (which 013's glossary entry #3 forbids). After this story lands, the LLM gets ONE internally-consistent recommended path: `master_fact → release_fact (on master_id) → release_artist_bridge (on release_id)`. The contradiction the LLM resolved by hallucinating a forbidden join is closed at its source.

**Independent Test**: re-run the question *"top 5 artists with works having the most versions, excluding 'Various' and 'Unknown Artist'"* through the post-US1 agent. The generated SQL MUST use `release_fact` as the master → bridge traversal, MUST NOT contain `release_unique_view` in a JOIN, AND MUST NOT contain any predicate of the form `master_fact.<id_col> = release_*_bridge.<id_col>`. Per spec §SC-001 (live), SC-006/SC-007 (renderer-level).

### Tests for User Story 1

> **NOTE: Update these test assertions BEFORE or alongside the renderer change.** The two phrase assertions in `test_schema_context.py` currently lock the pre-014 wording — they will fail when T005 lands until T004 updates them.

- [X] T004 [P] [US1] Update `agent/tests/unit/test_schema_context.py` per [research.md §R7 table B](./research.md): two phrase assertions in `test_join_graph_section_present_when_master_fact_true` (lines around 152–185) — replace the assertion on `"master_fact -> release_unique_view (on master_id)"` with `"master_fact -> release_fact (on master_id)"`; replace the assertion that checks for the pre-014 "Prefer release_unique_view" line with a new assertion that the cross-grain section contains the substring `"release_unique_view is NOT a usable traversal surface"`. The forbidden-joins assertion (around lines 183–184) is unchanged.

### Implementation for User Story 1

- [X] T005 [P] [US1] Edit `agent/src/discogs_agent/duckdb_layer/schema.py` — replace `_render_join_graph` lines 224–246 (the "Cross-grain traversal hints" sub-block) with the new wording per [research.md §R3](./research.md). The new sub-block: (a) preserves the "DIFFERENT identifier namespaces" line, (b) replaces the worked example to use `release_fact (on master_id) -> release_artist_bridge (on release_id)`, (c) adds the COUNT-pattern note about `COUNT(DISTINCT release_fact.master_id)` / `COUNT(DISTINCT release_fact.release_id)` and the release × style multiplication, (d) replaces the `"Prefer release_unique_view ... over release_fact"` line with the positive prohibition `"release_unique_view is NOT a usable traversal surface — it's only safe for single-release spot-checks (see glossary entry #3). Always traverse through release_fact for cross-grain joins."`, (e) preserves the bridge-cardinality line. Lines 198–222 (Edges sub-block) and lines 249–262 (Forbidden joins sub-block) are unchanged.
- [X] T006 [US1] Regenerate `agent/tests/integration/golden/schema_context_block.txt` per [quickstart.md §Step 3](./quickstart.md): `cd agent && UPDATE_GOLDEN=1 uv run pytest tests/integration/test_schema_context_join_graph.py`. Confirm the regenerated golden contains the new wording (`"master_fact -> release_fact (on master_id)"`, `"release_unique_view is NOT a usable traversal surface"`) and does NOT contain the legacy `"Prefer release_unique_view"` line. Then re-run `uv run pytest tests/integration/test_schema_context_join_graph.py -v` — all 4 tests MUST pass without `UPDATE_GOLDEN=1`. Depends on T005 being committed first.

**Checkpoint**: At this point, US1 is fully functional and testable independently via [quickstart.md §§ 1–4](./quickstart.md). The reported regression (run `2557c2ce-...`) is closed at the prompt-steering layer.

---

## Phase 4: User Story 2 — Static forbidden-join enforcement (Priority: P2)

**Goal**: The `sql_safety_checker` rejects SQL containing forbidden cross-grain join predicates (e.g., `master_fact.master_id = release_artist_bridge.release_id`, with or without aliases) at safety-check time. Even when prompt steering fails for a question class 014's hint update didn't anticipate, the safety checker bites and forces a retry instead of shipping a silent wrong answer.

**Independent Test**: Pass the exact SQL from run `2557c2ce-...` (with aliases `mf`, `rab`) directly into `sql_safety_checker` via unit test. Output MUST contain `allowed=False` with exactly one `SafetyViolation` of `rule="forbidden_join"` and a detail string of the form `"master_fact.master_id = release_artist_bridge.release_id"`. The label-bridge and `main_release_id` variants MUST fire the same rule. A legitimate `release_fact.release_id = release_artist_bridge.release_id` join MUST NOT fire the rule. Per spec §SC-004, SC-005.

### Tests for User Story 2

- [X] T007 [P] [US2] Add 6 new test cases to `agent/tests/unit/test_sql_safety_checker.py` per [research.md §R7 table A](./research.md): (1) the exact SQL from run `2557c2ce-...` with aliases `mf`, `rab` — expect single `forbidden_join` violation; (2) label-bridge variant fully qualified — same rule; (3) `main_release_id` variant with aliases — same rule with hint in detail; (4) legitimate `release_fact.release_id = release_artist_bridge.release_id` join — no `forbidden_join` violation (regression guard); (5) CTE-indirected forbidden join — marked `pytest.mark.skip(reason="known regex-scanner gap; tracked in 014/research.md §R1")` and documents the gap; (6) `has_master_fact = False` schema context — `forbidden_join` rule does NOT fire (conditional verified). Place the new cases at the end of the existing test module, after the post-line-189 area noted in the Explore findings.

### Implementation for User Story 2

- [X] T008 [P] [US2] Edit `agent/src/discogs_agent/tools/sql_safety_checker.py` per [research.md §R1, R4, R5, R6](./research.md) and [contracts/amendment-004-sql-safety.md §3.2.4](./contracts/amendment-004-sql-safety.md). Add at module level: the constant `_FORBIDDEN_JOIN_PAIRS` (tuple of 4 tuples per data-model.md Entity 3). Add helper functions: `_strip_comments(sql) -> str` using `sqlparse.format(sql, strip_comments=True)`; `_build_alias_map(sql) -> dict[str, str]` scanning `FROM <table> [AS] <alias>` and `JOIN <table> [AS] <alias>` patterns; `_scan_forbidden_joins(sql, has_master_fact) -> list[SafetyViolation]` that orchestrates strip-comments → build-alias-map → scan-ON-predicates → match against `_FORBIDDEN_JOIN_PAIRS` (both orientations) → emit violations with canonical unqualified-table detail strings, with the `main_release_id` legitimate-sometimes hint appended where applicable. Call `_scan_forbidden_joins` in the main checker pipeline (around line 287, after `_scan_forbidden_tables` and before the success return). Re-run T007 — at least 5 cases MUST pass; the CTE-indirection case remains skipped.

**Checkpoint**: At this point, US2 is fully functional and verifiable via [quickstart.md §§ 1, 9](./quickstart.md). The defense-in-depth net is in place.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Apply the three upstream-contract amendments, perform the renumbering admin, validate the whole feature end-to-end via the quickstart procedure, and confirm checklists are still green.

### Upstream contract amendments

- [X] T009 [P] Apply the contract amendment to `specs/005-agent-schema-context/contracts/schema-context.md` per [contracts/amendment-005-schema-context.md](./contracts/amendment-005-schema-context.md). Replace the example block's cross-grain traversal hints sub-block with the new wording. Replace the normative requirements section's bullet list. The forbidden-joins section is unchanged.
- [X] T010 [P] Apply the contract amendment to `specs/004-agent-v1/contracts/sql-safety.md` per [contracts/amendment-004-sql-safety.md](./contracts/amendment-004-sql-safety.md). Insert a new §2.4 "Forbidden cross-grain joins" after §2.3; insert a new §3.2.4 "Forbidden-join scan" after §3.2.3; add the `forbidden_join` row to the §4 verdict-table; add the new test-case requirements to §6.
- [X] T011 NOTE: The 009 supersession is fully captured in `014/contracts/amendment-009-cross-grain-hint.md` (already written by `/speckit-plan`). Per Constitution VI's "predecessor specs' artifacts are frozen" guidance, the `specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md` document is NOT modified. This task is a verification step: confirm by `git diff --stat -- specs/009-schema-context-join-graph/` returns empty after all other tasks have landed.

### Renumbering admin (FR-018)

- [X] T012 Perform the renumbering admin per [contracts/renumbering-013-pointer.md](./contracts/renumbering-013-pointer.md). Run: `git mv specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md`. Then edit the renamed file: replace every occurrence of `014-release-unique-view-materialization` with `015-release-unique-view-materialization` (at least 2 occurrences — document title + provisional-naming section). Add a new historical-context note at the top of the file per renumbering-013-pointer.md §"New historical-context note".

### Verification (code-level — runnable without live infra)

- [X] T013 Run [quickstart.md](./quickstart.md) Steps 1–6 — new unit tests pass, integration golden in sync, new wording grep-confirmed in both renderer + golden, legacy wording absent from both, forbidden-joins block still intact, renumbered pointer file present with correct content, upstream contract amendments applied. Per spec SC-006, SC-007, SC-008.
- [X] T014 Run [quickstart.md](./quickstart.md) Step 7 — full agent test suite passes with the expected count (baseline `143 passed, 2 skipped` becomes at least `148 passed, 2 skipped` post-014 — 5 new passing tests + 1 new skipped test). Per spec SC-009.

### Verification (live-infra — deferred to operator-side execution)

- [X] T015 Run [quickstart.md](./quickstart.md) Step 8 — live replay of the triggering question via the running agent API. Confirm `status: "succeeded"`; confirm `generated_sql` uses `release_fact` traversal and contains no forbidden-join predicate. Per spec SC-001.
- [X] T016 Run [quickstart.md](./quickstart.md) Step 9 — verify the safety checker actually fired the `forbidden_join` rule in production by inspecting the most recent `agent_tool_calls` row with `output_json @> '{"allowed": false}'`. Per spec SC-004 (production verification).
- [X] T017 Run [quickstart.md](./quickstart.md) Step 10 — five-question regression probe (the trigger case + 4 additional master→artist/master→label questions). All MUST return `status: "succeeded"` and `has_forbidden_join: false`. Per spec SC-002.
- [X] T018 Run [quickstart.md](./quickstart.md) Step 11 — re-run the seven curated demo questions from `008/contracts/curated-questions.md`. All MUST return `succeeded` (or `succeeded_empty` where appropriate). None should hit the new `forbidden_join` rule. Per spec SC-003 (no regressions).

### Final checklist hygiene

- [X] T019 [P] Re-validate `specs/014-cross-grain-join-postmortem/checklists/requirements.md` — all 14 items should remain `[x]`. If any drifted to `[ ]` during implementation, update the spec and re-validate before merge.
- [X] T020 [P] Confirm CLAUDE.md's SPECKIT block reflects 014 as the current in-flight feature — `grep -A 2 "014-cross-grain-join-postmortem" CLAUDE.md` should show the in-flight paragraph added by `/speckit-plan`. The 015 reference (renumbered ETL follow-on) should also be visible in the 013 predecessor paragraph.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion. Single verification task (T003) — fast.
- **User Stories (Phase 3 — US1, Phase 4 — US2)**: BOTH depend on Foundational completion. The two stories are fully independent (different files, no shared state). They can run in parallel by two developers, or sequentially by one. The spec assigns US1=P1 (the immediate fix), US2=P2 (defense-in-depth).
- **Polish (Phase 5)**: T009 and T010 (upstream amendments) depend on US1+US2 being committed (the amendments must reflect the deployed code). T011 (009 verification) depends on all other Polish tasks. T012 (renumbering admin) can run any time after T003. T013–T014 (code-level quickstart) depend on US1+US2 + T009+T010+T012 being committed. T015–T018 (live-infra quickstart) depend on T013+T014 succeeding and the live stack being running. T019–T020 are pure verification; can run any time.

### User Story Dependencies

- **US1 (T004–T006)**: Independent of US2 entirely. Touches `schema.py`, `test_schema_context.py`, and the integration golden. No files overlap with US2.
- **US2 (T007–T008)**: Independent of US1 entirely. Touches `sql_safety_checker.py` and `test_sql_safety_checker.py`. No files overlap with US1.

### Within Each User Story

**US1 (Phase 3)**:
- T004 (test assertion update) and T005 (renderer edit) can run in parallel — different files. The test assertions are designed to match the post-T005 wording; running T004 before T005 means the test fails until T005 lands.
- T006 (golden regeneration) depends on T005 being committed (the golden is captured from the live renderer output).

**US2 (Phase 4)**:
- T007 (new test cases) and T008 (implementation) can run in parallel — different files. The new test cases are designed to exercise the post-T008 implementation; running T007 before T008 means the tests fail until T008 lands.
- T008 itself is a single-file edit (sql_safety_checker.py) but has multiple internal changes (constant + 3 helper functions + 1 pipeline-call edit). Keep them in one commit since they're conceptually one change.

### Parallel Opportunities

- Setup (T001, T002) is sequential — both must complete before Phase 2.
- Foundational (T003) is a single verification step.
- US1 and US2 entire phases can run in parallel by two developers (different files, no overlap).
- Within US1: T004 ∥ T005 — different files. T006 sequential after T005.
- Within US2: T007 ∥ T008 — different files.
- Polish: T009 ∥ T010 ∥ T012 ∥ T019 ∥ T020 are all independent of each other (different files). T011 is verification-only. T013–T018 are sequential (running through the quickstart).

---

## Parallel Example: User Story 1

```bash
# Two parallel edits in different files:
Task: "Update test_schema_context.py phrase assertions per T004"
Task: "Edit _render_join_graph in schema.py per T005"

# After T005 commits: regenerate the integration golden:
Task: "Regenerate schema_context_block.txt per T006"
```

## Parallel Example: User Story 2

```bash
# Two parallel edits in different files:
Task: "Add 6 new test cases to test_sql_safety_checker.py per T007"
Task: "Add _FORBIDDEN_JOIN_PAIRS + helpers + new pass to sql_safety_checker.py per T008"
```

## Parallel Example: Polish phase

```bash
# Three parallel upstream-doc edits (different spec files):
Task: "Apply amendment-005 to specs/005-.../schema-context.md per T009"
Task: "Apply amendment-004 to specs/004-.../sql-safety.md per T010"
Task: "Renumber 013's successor-014-pointer.md → successor-015-pointer.md per T012"
```

---

## Implementation Strategy

### MVP First (US1 alone)

The spec assigns US1=P1 (closes the reported regression) and US2=P2 (defense-in-depth). US1 alone is a valid MVP:

1. Complete Phase 1 + Phase 2 (Setup + Foundational).
2. Complete Phase 3 (US1) — three tasks: test update + renderer edit + golden regen.
3. STOP and VALIDATE — replay the triggering question; confirm the forbidden-join predicate is no longer generated.
4. Ship. The reported regression is closed. US2 can land as a follow-up commit on the same branch or as a separate PR.

### Incremental Delivery

Two commits on the same branch:

1. **Commit 1 (MVP)**: Setup + Foundational + US1 + the relevant Polish (T009 amendment-005, T012 renumbering). Closes the bug as observed.
2. **Commit 2 (Defense-in-depth)**: US2 + T010 amendment-004 + T013–T014 code-level quickstart. Adds the safety-checker rule.

T015–T018 (live-infra quickstart) and T019–T020 (final checklist) gate both commits at the operator level — they're not part of the implementation commits.

### Parallel Team Strategy

With two developers available:

1. Both pair on Phase 1 + Phase 2 (~5 minutes total).
2. Developer A takes Phase 3 (US1), Developer B takes Phase 4 (US2). Independent files; no merge conflicts.
3. Either developer takes Phase 5 (Polish). T009, T010, T012 can be done by either; T013–T018 are sequential quickstart runs (one developer per the live stack).

---

## Notes

- **[P] tasks** = different files, no dependencies on incomplete tasks.
- **[Story] label** maps task to US1 (cross-grain hint) or US2 (forbidden-join enforcement). Setup, Foundational, and Polish phases have NO story label.
- **No new files** in `agent/`. All US1 + US2 implementation lands in existing files (schema.py, sql_safety_checker.py, two test modules). The two new contract documents (amendment-004-sql-safety.md, renumbering-013-pointer.md) live in 014's `contracts/` directory and were written during `/speckit-plan`.
- **Test ordering** (per research.md §R7): the unit-test updates (T004, T007) target the post-implementation wording / behavior. Running them before the implementation lands means they FAIL until the impl ships. This is the TDD-style ordering the spec implies; not strictly required for a single-Claude implementation flow but is the right ordering for a reviewer.
- **Renumbering admin (T012)** can run independently of any other task. It's purely documentation maintenance; no code or test dependency.
- **Commit boundaries**: split by concern per project memory `feedback_commit_splitting.md`. Suggested splits:
  1. US1 + amendment-005 + renumbering admin (one logical change: "fix the contradiction at the source").
  2. US2 + amendment-004 (one logical change: "add the safety net").
  Or, more granular:
  1. Renumbering admin (T012) — pure housekeeping.
  2. US1 (T004, T005, T006) + amendment-005 (T009).
  3. US2 (T007, T008) + amendment-004 (T010).
- **Avoid**: editing US1 and US2 surfaces in the same commit (mixes concerns); skipping T002 baseline (any regression caught only at Phase 5 will be costly to bisect); editing `agent/tests/integration/test_schema_context_join_graph.py` (its assertions on the namespaces-different line and the forbidden-joins lines are unchanged by 014 — only the golden contents change).
