---

description: "Task list for 013-filtered-aggregation-postmortem: sandbox OOM observability + glossary follow-on to 012"
---

# Tasks: Filtered-aggregation postmortem — sandbox OOM observability + glossary follow-on

**Input**: Design documents from `/specs/013-filtered-aggregation-postmortem/`
**Plan**: [plan.md](./plan.md)
**Spec**: [spec.md](./spec.md)
**Research**: [research.md](./research.md)
**Data model**: [data-model.md](./data-model.md)
**Contracts**: [contracts/amendment-004-code-generation.md](./contracts/amendment-004-code-generation.md), [contracts/amendment-005-schema-context.md](./contracts/amendment-005-schema-context.md), [contracts/sandbox-exception-taxonomy.md](./contracts/sandbox-exception-taxonomy.md), [contracts/successor-014-pointer.md](./contracts/successor-014-pointer.md)
**Quickstart**: [quickstart.md](./quickstart.md)

**Tests**: Tests ARE included — research.md §R8 explicitly calls for new unit-test modules for the runner signal-mapping branch (`test_sandbox_signal_mapping.py`) and the validator named-rule branch (`test_chart_validator_oom_rule.py`). Integration test coverage is provided by regenerating the existing schema-context golden.

**Organization**: Two user stories (both P1, tied priority, fully independent — different files). US1 is observability; US2 is glossary tightening. They can be implemented in either order or in parallel by two developers. Polish phase exercises both via the quickstart procedure.

---

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 = observability, US2 = glossary)
- Setup, Foundational, and Polish phases have NO story label

## Path Conventions

This feature lives entirely within the `agent/` component (Constitution Principle VI). Paths are repo-relative; key surfaces:

- Production code: `agent/src/discogs_agent/{sandbox,tools,graph/nodes,duckdb_layer,prompts}/`
- Tests: `agent/tests/unit/` (new modules), `agent/tests/integration/golden/` (golden regenerated)
- Documentation: `specs/004-agent-v1/contracts/`, `specs/005-agent-schema-context/contracts/`, `specs/008-agent-frontend-v1/contracts/`, `specs/013-filtered-aggregation-postmortem/contracts/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Ensure the branch is in a clean state and the 013 design artifacts are visible to the implementer.

- [X] T001 Verify branch is `013-filtered-aggregation-postmortem` and working tree has only expected pending changes — run `git status` and `git branch --show-current`; the only un-committed items should be the spec/plan/contracts written during `/speckit-specify` and `/speckit-plan` (which a `/speckit-git-commit` hook would have committed if invoked).
- [X] T002 Run the existing agent unit + integration test suite from a baseline checkout to confirm green-before-013 — `cd agent && uv run pytest tests/unit tests/integration -q`. Record the test count; the 013 implementation MUST land with the same count + new tests, all passing.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No code-side prerequisites — the four contract documents under `specs/013-filtered-aggregation-postmortem/contracts/` (written during `/speckit-plan`) are the foundational design artifacts and are already in place. This phase is a single verification step.

**⚠️ CRITICAL**: No user story work should begin until this verification passes.

- [X] T003 Verify the four 013 contract documents exist and are non-empty — `ls -la specs/013-filtered-aggregation-postmortem/contracts/` MUST list `amendment-004-code-generation.md`, `amendment-005-schema-context.md`, `sandbox-exception-taxonomy.md`, `successor-014-pointer.md`. Read each and confirm it matches the spec's FR-012 through FR-015 surfaces. If any is missing or stale, return to `/speckit-plan`.

**Checkpoint**: Foundation ready — US1 and US2 can now proceed in parallel.

---

## Phase 3: User Story 1 — Sandbox OOM observability (Priority: P1) 🎯 MVP-eligible

**Goal**: When the kernel cgroup OOM-killer SIGKILLs the sandbox subprocess, the agent's run record, validator output, and final user-facing response name the cause (`oom_killed`) instead of producing the opaque legacy three-error pile (`nonzero_exit` + `exception_raised` + `result_missing`). Operator triage on a failed run drops to a single inspection step.

**Independent Test**: Inducing an OOM-killed sandbox run (deliberately memory-heavy query, or replay of the Depeche Mode run on the post-013 codebase) MUST produce `agent_tool_calls.output_json.exception_type == "oom_killed"` for the `sandbox_executor` row, AND `chart_validator` errors[] containing exactly ONE rule of `"oom_killed"`, AND `agent_runs.final_response` containing one of `memory`, `too heavy`, `narrow your question`, `reduce scope`. Per spec §SC-001, SC-005, SC-006.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation.** Both test modules are NEW files; the tested code paths do not yet exist.

- [X] T004 [P] [US1] Create new unit-test module `agent/tests/unit/test_sandbox_signal_mapping.py` per [research.md §R8](./research.md) and [contracts/sandbox-exception-taxonomy.md §Unit-test coverage](./contracts/sandbox-exception-taxonomy.md). Five test cases: (a) `exit_code=-9` + `harness_timeout_fired=False` → `("oom_killed", <non-empty message>)`; (b) `exit_code=-9` + `harness_timeout_fired=True` → `("timeout", _)`; (c) `exit_code=-11` + `harness_timeout_fired=False` → `("sandbox_signaled", <message containing "signal 11">)`; (d) `exit_code=1` → `("nonzero_exit", "exit_code=1")` regression guard; (e) `exit_code=0` + `parsed_error="BinderError"` → `("BinderError", _)` regression guard.
- [X] T005 [P] [US1] Create new unit-test module `agent/tests/unit/test_chart_validator_oom_rule.py` per [research.md §R8](./research.md). Two test cases: (a) feed a `SandboxOutcome`-shaped dict with `exception_type="oom_killed"` → `errors` contains exactly one entry with `rule="oom_killed"`, NOT the legacy three-error layering; (b) feed `exception_type="nonzero_exit"` → legacy three-error layering preserved (regression guard).

### Implementation for User Story 1

- [X] T006 [P] [US1] Edit `agent/src/discogs_agent/sandbox/runner.py` — extend the catch-all branch at approximately line 137 (the `if exit_code != 0 and exception_type is None:` block) to map `exit_code < 0` to signal-aware named values per [contracts/sandbox-exception-taxonomy.md §Mapping from exit_code to exception_type](./contracts/sandbox-exception-taxonomy.md): `exit_code == -9` → `exception_type = "oom_killed"` with message `"kernel SIGKILL (cgroup OOM-killer); exit_code=-9; sandbox exceeded memory budget"`; any other `exit_code < 0` → `exception_type = "sandbox_signaled"` with message `f"sandbox killed by signal {-exit_code}; exit_code={exit_code}"`. Positive non-zero `exit_code` remains labeled `"nonzero_exit"` with the existing `f"exit_code={exit_code}"` message. The harness's own `subprocess.TimeoutExpired` path at lines 102–108 is unchanged (sets `exception_type = "timeout"` BEFORE the catch-all). Re-run T004 — it MUST now pass.
- [X] T007 [P] [US1] Edit `agent/src/discogs_agent/tools/chart_validator.py` — at the `if er.get("exit_code") != 0` / `if er.get("exception_type")` blocks (approximately lines 58–69), add a short-circuit branch BEFORE the legacy three-error layering: when `er.get("exception_type") == "oom_killed"`, emit exactly ONE `ValidationError(rule="oom_killed", detail=er.get("exception_message", ""))` and skip the layered emissions. The `result_missing` rule is also skipped on this path (the OOM rule subsumes it). For all other `exception_type` values, the legacy layering remains. Re-run T005 — it MUST now pass.
- [X] T008 [P] [US1] Edit `agent/src/discogs_agent/graph/nodes/response_synthesizer.py` — extend `_build_result_block` (around line 92) with a new `elif` branch parallel to the existing `succeeded_empty` case at line 102: when `validation_result.errors[]` contains any entry with `rule == "oom_killed"`, append a memory-pressure diagnostic hint to the result block. Exact wording per [research.md §R3](./research.md):

  > *Diagnostic hint: the query exceeded the sandbox's memory budget and was terminated by the kernel. This usually means the query touched too many rows. Try narrowing the scope — filter to a single artist, year, country, or genre — or ask for a smaller slice of the catalog.*

  The branch order: `is_empty` → new OOM branch → `validation.get("valid")`. The result_block is the LLM's grounding; the response synthesizer's prompt instructs it to paraphrase, so the user-facing `final_response` will reflect this hint in the model's own voice.

**Checkpoint**: At this point, US1 is fully functional and testable independently via the steps in [quickstart.md §Step 6](./quickstart.md).

---

## Phase 4: User Story 2 — `release_unique_view` blocked in joins/group-bys regardless of filters (Priority: P1)

**Goal**: The Depeche Mode question — and the broader class of single-artist version-spread questions — succeeds end-to-end because the LLM no longer has a "but my query is filtered, so it's fine" loophole. Glossary entry #3 forbids `release_unique_view` in any JOIN or GROUP BY regardless of WHERE filters; the spot-check carve-out for `WHERE release_id = <literal>` remains.

**Independent Test**: Running the Depeche Mode question end-to-end produces `agent_runs.status == "succeeded"` AND the generated SQL contains no `release_unique_view` reference in JOIN or GROUP BY positions. Per spec §SC-002, SC-003. Five-question regression probe per quickstart Step 8.

### Tests for User Story 2

> **NOTE**: No new unit-test modules required for US2 — the integration golden snapshot at `agent/tests/integration/golden/schema_context_block.txt` (regenerated in T013) is the locking test, and the existing `test_rendered_block_matches_golden` integration test will fail on golden divergence until T008 (renderer) and T013 (golden) are both committed.

### Implementation for User Story 2

- [X] T009 [P] [US2] Edit `agent/src/discogs_agent/duckdb_layer/schema.py` — replace `_DOMAIN_GLOSSARY` entry #3 with the new wording per [research.md §R5](./research.md) and [contracts/amendment-005-schema-context.md](./contracts/amendment-005-schema-context.md). Three deltas from the 012 wording: (1) `for catalog-wide aggregations` → `in any JOIN or GROUP BY, regardless of WHERE filters`; (2) `spills GBs of temp even for trivial GROUP BYs` → `typically OOMs the sandbox even when the query has selective WHERE clauses on a joined table (the planner cannot push the predicate through the view's DISTINCT)`; (3) `is fine for spot-check queries against a single release ... but never for catalog-wide GROUP BYs` → `is ONLY safe for spot-check queries that filter directly on a single release literal`. The carve-out example syntax updates to `SELECT * FROM release_unique_view WHERE release_id = N`. Full byte-equivalent text in research.md §R5.
- [X] T010 [P] [US2] Edit `agent/src/discogs_agent/prompts/code_generator.md` — replace the "Critical rule for counting releases" bullet (currently lines 6–17, "DO NOT use `release_unique_view` for catalog-wide aggregations") with the paraphrase wording per [research.md §R6](./research.md). Key clause: "DO NOT use `release_unique_view` in any JOIN or GROUP BY, regardless of WHERE filters — its `SELECT DISTINCT *` definition materializes the full 19M-row set and OOMs the sandbox even on filtered queries. The view is ONLY safe for spot-check queries that filter directly on a single release literal (e.g., `WHERE release_id = 12345`)." Preserve the rest of the prompt unchanged.
- [X] T011 [P] [US2] Edit `agent/src/discogs_agent/prompts/repair_code.md` — replace the Critical-rules bullet at lines 37–42 with the same paraphrase wording as T010 per [research.md §R6](./research.md). Byte-equivalent to T010's edit on the load-bearing clause. The rest of the prompt (the `{failure_details}` interpolation, the analytical-plan preservation directive, etc.) is unchanged.
- [X] T012 [P] [US2] Edit `specs/008-agent-frontend-v1/contracts/curated-questions.md` line 18 — replace the Q1 description from `Basic decade-grain trend using release_unique_view.` to `Basic decade-grain release count using COUNT(DISTINCT release_id) FROM release_fact GROUP BY decade.` per [research.md §R7](./research.md) (FR-011). No frontend code is affected; this is documentation cleanup. Verify with `grep -n release_unique_view specs/008-agent-frontend-v1/contracts/curated-questions.md` — the Q1 section (lines 13–22) MUST NOT contain `release_unique_view` after the edit; other Q sections may.
- [X] T013 [US2] Regenerate `agent/tests/integration/golden/schema_context_block.txt` to match the new `_DOMAIN_GLOSSARY` entry #3 from T009 (FR-010). Run the existing golden-regeneration script (or `pytest --snapshot-update` if applicable; check `agent/tests/integration/conftest.py` for the regeneration helper). Then run `cd agent && uv run pytest tests/integration/test_rendered_block_matches_golden.py -v` — MUST pass. Depends on T009 being committed first.

**Checkpoint**: At this point, US2 is fully functional. Running [quickstart.md §Step 5](./quickstart.md) replays the Depeche Mode question and inspects the generated SQL — it MUST count versions via `release_fact` + `release_artist_bridge` with no `release_unique_view` in JOIN or GROUP BY positions.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Apply the upstream-contract amendments, validate the whole feature end-to-end via the quickstart procedure, and confirm checklists are still green.

- [X] T014 [P] Apply the contract amendment to `specs/005-agent-schema-context/contracts/schema-context.md` per [contracts/amendment-005-schema-context.md](./contracts/amendment-005-schema-context.md). Replace the example block's glossary entry #3 with the new byte-equivalent wording. This is the second-round rewrite (012 did round one); the contract should NO LONGER contain the "for catalog-wide aggregations" qualifier.
- [X] T015 [P] Apply the contract amendment to `specs/004-agent-v1/contracts/code-generation.md` per [contracts/amendment-004-code-generation.md](./contracts/amendment-004-code-generation.md). Extend the §3.4 "Failure modes" table with two new rows (`oom_killed`, `sandbox_signaled`) and one clarified row (positive non-zero exit labeled `"nonzero_exit"`); add the new §3.4.1 "Signal-aware failure mapping" subsection immediately after the §3.4 table. The §3.4.1 prose is provided verbatim in the amendment document.
- [X] T016 Run [quickstart.md](./quickstart.md) Steps 1–4 end-to-end — unit tests, golden test, glossary-mirror grep checks, Q1 description grep check. All MUST pass. Per spec SC-007.
- [X] T017 Run [quickstart.md](./quickstart.md) Step 5 — replay the Depeche Mode question end-to-end via the running agent API. Confirm `status: "succeeded"` and that `generated_sql` contains no `release_unique_view` in JOIN or GROUP BY positions. Per spec SC-002.
- [X] T018 Run [quickstart.md](./quickstart.md) Step 6 — induce an OOM-killed run (via the developer harness or via a deliberately-pathological question), then inspect the resulting `agent_runs` and `agent_tool_calls` rows. Confirm `sandbox_executor.output_json.exception_type == "oom_killed"`, `chart_validator.output_json.errors[]` contains exactly one rule of `"oom_killed"`, and `agent_runs.final_response` contains memory-pressure language. Per spec SC-001, SC-005, SC-006.
- [X] T019 Run [quickstart.md](./quickstart.md) Step 7 — execute all seven curated demo questions from `008/contracts/curated-questions.md`. All MUST return `status: "succeeded"` (or `"succeeded_empty"` if appropriate). Per spec SC-004 (no regressions).
- [X] T020 Run [quickstart.md](./quickstart.md) Step 8 — execute the five-question single-artist version-spread regression probe. All MUST return `status: "succeeded"` AND `generated_sql` MUST NOT reference `release_unique_view` in JOIN or GROUP BY positions. Per spec SC-003.
- [X] T021 [P] Re-validate `specs/013-filtered-aggregation-postmortem/checklists/requirements.md` — all items should remain `[x]`. If any drifted to `[ ]` during implementation (e.g., a new clarification surfaced), update the spec and the checklist before merge.
- [X] T022 [P] Confirm CLAUDE.md's SPECKIT block reflects 013's status — `grep -A 2 "013-filtered-aggregation-postmortem" CLAUDE.md` should show the in-flight paragraph and the plan-file pointer added by `/speckit-plan`. No further edits needed unless 013's status changes from "in-flight" to "merged."

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion. Single verification task (T003) — fast.
- **User Stories (Phase 3 — US1, Phase 4 — US2)**: BOTH depend on Foundational completion. The two stories are fully independent: different files, no shared state. They can run in parallel by two developers, or sequentially by one. **The spec ties them at P1**; the implementation order is dictated by team capacity, not by priority.
- **Polish (Phase 5)**: T014, T015 depend on US2 completion (amendments must reflect the deployed wording). T016–T020 depend on BOTH US1 and US2 being committed (the quickstart exercises both). T021, T022 are pure verification; can run any time.

### User Story Dependencies

- **US1 (T004–T008)**: Independent of US2 entirely. Touches `sandbox/runner.py`, `tools/chart_validator.py`, `graph/nodes/response_synthesizer.py`, and two new test modules in `tests/unit/`. No files overlap with US2.
- **US2 (T009–T013)**: Independent of US1 entirely. Touches `duckdb_layer/schema.py`, two `prompts/*.md` files, the integration golden, and one line in `008/contracts/curated-questions.md`. No files overlap with US1.

### Within Each User Story

**US1 (Phase 3)**:
- T004 and T005 (new test modules) can run in parallel. Both can be authored BEFORE T006/T007/T008 (TDD: tests fail until implementation lands).
- T006 (runner edit) unblocks T004's last failing assertion.
- T007 (validator edit) unblocks T005's last failing assertion.
- T008 (synthesizer edit) has no new unit-test module; integration validation comes from quickstart Step 6 (T018).
- T006, T007, T008 touch different files — can be edited in parallel, but their commits should be logically grouped per `git commit` boundary.

**US2 (Phase 4)**:
- T009, T010, T011, T012 touch different files — fully parallel.
- T013 (golden regeneration) depends on T009 being committed (the golden is derived from the renderer output).

### Parallel Opportunities

- All Setup tasks (T001, T002) are sequential — both must complete before Phase 2.
- T003 (Foundational) is a single verification step.
- US1 and US2 entire phases can run in parallel by two developers (different files, no overlap).
- Within US1: T004 ∥ T005 ∥ T006 ∥ T007 ∥ T008 — all touch different files. The test/implementation order within a single developer's workflow is TDD-style (test first, then impl). For two devs splitting US1, one can take T004 + T006, the other T005 + T007, and either can take T008.
- Within US2: T009 ∥ T010 ∥ T011 ∥ T012 — four parallel edits; T013 is the only sequential step (golden regeneration after T009).
- Polish: T014 ∥ T015 ∥ T021 ∥ T022 are all independent. T016–T020 are sequential (running through the quickstart).

---

## Parallel Example: User Story 1

```bash
# Three parallel edits in different files (US1 implementation):
Task: "Edit agent/src/discogs_agent/sandbox/runner.py per T006"
Task: "Edit agent/src/discogs_agent/tools/chart_validator.py per T007"
Task: "Edit agent/src/discogs_agent/graph/nodes/response_synthesizer.py per T008"

# Two parallel new test modules (US1 tests):
Task: "Create agent/tests/unit/test_sandbox_signal_mapping.py per T004"
Task: "Create agent/tests/unit/test_chart_validator_oom_rule.py per T005"
```

## Parallel Example: User Story 2

```bash
# Four parallel edits in different files (US2 implementation, except T013):
Task: "Edit agent/src/discogs_agent/duckdb_layer/schema.py per T009"
Task: "Edit agent/src/discogs_agent/prompts/code_generator.md per T010"
Task: "Edit agent/src/discogs_agent/prompts/repair_code.md per T011"
Task: "Edit specs/008-agent-frontend-v1/contracts/curated-questions.md per T012"

# After T009 commits: regenerate the integration golden:
Task: "Regenerate agent/tests/integration/golden/schema_context_block.txt per T013"
```

## Parallel Example: Polish phase amendments

```bash
# Two parallel upstream-contract edits (different spec files):
Task: "Apply amendment-005 to specs/005-agent-schema-context/contracts/schema-context.md per T014"
Task: "Apply amendment-004 to specs/004-agent-v1/contracts/code-generation.md per T015"
```

---

## Implementation Strategy

### MVP First (either user story alone is shippable)

This feature is unusual: both user stories are P1 and both are independently demo-relevant. Two valid MVPs:

**MVP-A — US2 only (glossary tightening)**
1. Complete Phase 1 + Phase 2 (Setup + Foundational).
2. Complete Phase 4 (US2) — five small edits + golden regeneration.
3. STOP and VALIDATE — replay Depeche Mode question; the curated demo set still passes.
4. Ship. The Demo Day blocker is closed. Operator triage remains opaque on the rare OOM that slips through, but that's an acceptable known gap.

**MVP-B — US1 only (observability)**
1. Complete Phase 1 + Phase 2.
2. Complete Phase 3 (US1) — three code edits + two new test modules.
3. STOP and VALIDATE — induce an OOM; confirm named cause flows through.
4. Ship. The next OOM (and there WILL be one without US2) produces a diagnosable named cause and a memory-pressure user hint.

**Recommended**: ship both together as a single PR. The combined surface is ~10 file edits + 4 new files; manageable scope.

### Incremental Delivery

If shipping incrementally:

1. **Ship Phase 1 + 2 + Phase 4 (US2) first** — closes the Demo Day blocker. ~5 files changed, ~30 minutes coding time, ~15 minutes test time.
2. **Then Phase 3 (US1)** — adds operator observability. ~5 files changed (including 2 new test modules), ~30 minutes coding time, ~15 minutes test time.
3. **Then Phase 5 (Polish)** — applies upstream contract amendments and runs end-to-end quickstart. ~2 file edits + ~15 minutes quickstart time.

### Parallel Team Strategy

With two developers available:

1. Both pair on Phase 1 + Phase 2 (~5 minutes total).
2. Developer A takes Phase 3 (US1), Developer B takes Phase 4 (US2). Independent files; no merge conflicts.
3. Either developer takes Phase 5 (Polish). T014 and T015 can be done by either; T016–T020 are sequential quickstart runs (one developer).

---

## Notes

- **[P] tasks** = different files, no dependencies on incomplete tasks.
- **[Story] label** maps task to US1 (observability) or US2 (glossary). Setup, Foundational, and Polish phases have NO story label.
- **Two new files only**: `tests/unit/test_sandbox_signal_mapping.py` and `tests/unit/test_chart_validator_oom_rule.py`. Everything else is edits to existing files.
- **Verify tests fail before implementing** (TDD): T004 should fail until T006 lands; T005 should fail until T007 lands. The integration golden test (`test_rendered_block_matches_golden`) should fail after T009 commits and pass again after T013 regenerates the golden.
- **Commit boundaries**: split commits by concern per project memory `feedback_commit_splitting.md`. Suggested commits:
  1. US2 glossary + prompts + Q1 description + golden regeneration (one logical change).
  2. US1 runner + validator + synthesizer + tests (one logical change).
  3. Upstream contract amendments T014 + T015 (one back-fill commit).
- **Avoid**: editing US1 and US2 surfaces in the same commit (mixes concerns); skipping T002 baseline (any regression caught only at Phase 5 will be costly to bisect); editing `001/contracts/duckdb-schema.md` (out of scope — 013 does NOT touch ETL component contracts).
