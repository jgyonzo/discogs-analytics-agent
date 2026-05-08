# Tasks: JSONB NaN sanitization

**Input**: Design documents from `/specs/010-jsonb-nan-sanitization/`
**Prerequisites**:
- Plan: [plan.md](./plan.md)
- Spec: [spec.md](./spec.md)
- Research: [research.md](./research.md) (R1: TypeDecorator chokepoint; R2: two-layer test strategy; R3: pure-function sanitizer)
- Contracts: [contracts/amendment-004-postgres-schema.md](./contracts/amendment-004-postgres-schema.md) (verbatim §7 insertion text)
- Quickstart: [quickstart.md](./quickstart.md)

**Tests**: included — FR-010, FR-011 demand tests; SC-003, SC-005 are test-anchored. Tests are not optional for this feature.

**Components touched**: `agent/` only (Constitution Principle VI). Plus the `004/contracts/postgres-schema.md` amendment. No edits to `etl/`, `frontend/`, or any prompt template.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: US1, US2, US3.
- File paths are absolute relative to the repo root.

## Path Conventions

- Agent source: `agent/src/discogs_agent/persistence/`
- Agent tests: `agent/tests/unit/`, `agent/tests/integration/`
- Cross-feature contract amendment target: `specs/004-agent-v1/contracts/`

---

## Phase 1: Setup

No setup tasks. The `agent/` package, its dependency manifest, the `db_session` test fixture, and the SQLAlchemy + psycopg integration all exist from 004 + 005 + 006 + 007.

---

## Phase 2: Foundational

No foundational tasks. 010 introduces no new env vars, no new dependencies, no new modules — only one new utility file plus a small wrapping change in models.py.

---

## Phase 3: User Story 1 — Queries with NULL-containing dataframes complete successfully (Priority: P1) 🎯 MVP

**Goal**: The user's reported reproducer ("What are the top 15 countries by number of releases?") completes 200 with a populated chart artifact and a JSON-valid `dataframe_preview`. Same applies to any other query whose dataframe legitimately contains NULL cells.

**Independent Test**: Run the reproducer per [quickstart.md §1.3](./quickstart.md). PASS criteria: ≥9 of 10 attempts return HTTP 200 with `status: "succeeded"` AND zero `InvalidTextRepresentation` messages in the Postgres logs.

### Implementation for User Story 1

- [X] T001 [US1] Created `agent/src/discogs_agent/persistence/sanitize.py` with the pure `sanitize_for_jsonb(value: Any) -> Any` function. Stdlib-only (`math.isnan`, `math.isinf`). Recurses through `dict`, `list`, `tuple`. NaN/Infinity → None. Plus an explicit `bool` guard at the top because `bool` is a subclass of `int` (falls through to the catch-all `return value`, but the explicit guard documents the intent for the next reader). Module docstring references the 004 §7 amendment.

- [X] T002 [US1] Modified `agent/src/discogs_agent/persistence/models.py`. Added `_SanitizedJSON(TypeDecorator[dict[str, Any]])` with `impl = JSONB().with_variant(JSON(), "sqlite")`, `cache_ok = True`, and `process_bind_param` that returns `None` for `None` else `sanitize_for_jsonb(value)`. Exported `JSONType = _SanitizedJSON` so the five existing `mapped_column(JSONType, ...)` declarations work without edits. Added `from .sanitize import sanitize_for_jsonb` import. The existing `Dialect` import was already present from the `GUID` class.

- [X] T003 [US1] Applied the contract amendment to `specs/004-agent-v1/contracts/postgres-schema.md`. New §7 ("JSONB input invariant") inserted verbatim after the existing §6. Eight subsections per the amendment file: 7.1 the constraint, 7.2 the five JSONB columns, 7.3 the chokepoint, 7.4 sanitizer's contract, 7.5 backwards compatibility, 7.6 what this does NOT do, 7.7 disciplinary analog (VII.c write-side), 7.8 verification.

### Tests for User Story 1

- [X] T004 [P] [US1] Created `agent/tests/unit/test_jsonb_sanitizer.py` with 13 test cases (more than the spec's 6 minimum): the 6 named cases from the spec (top-level/nested/list/Infinity/idempotent-clean/no-mutate), plus `test_idempotent_on_dirty_input`, `test_preserves_clean_values`, `test_tuples_become_lists`, `test_handles_pydantic_model_dump_output` (locks in the actual upstream data shape), `test_returns_new_container_objects` (FR-005 strictness), `test_passes_through_unsupported_types_unchanged`, and a parametrized `test_scalar_floats` covering 6 scalar inputs.

- [X] T005 [P] [US1] Created `agent/tests/integration/test_jsonb_nan_persistence.py` with 3 test cases: (1) `test_tool_call_with_nan_output_json_persists_and_reads_back_clean` — production-shaped reproducer through `ToolCallRepo.create`; (2) `test_tool_call_with_clean_output_json_unchanged` — clean dicts pass through bit-exact (boundary idempotence); (3) `test_run_metadata_json_with_nan_persists_clean` — coverage for FR-006 breadth (also exercises `agent_runs.metadata_json` via `RunRepo.update_metadata`). Uses existing `db_session` SQLite fixture. Implementation note: had to consult the actual repo signatures (`ThreadRepo.create(metadata=...)`, `RunRepo.create(thread_id, user_query)` with no metadata kwarg, `ToolCallRepo.create(...)` with no `tool_call_id` kwarg — UUID generated internally) rather than guessing.

- [ ] T006 [US1] **Manual gate, deferred to PR review.** Run the reproducer 10 times against the live agent post-fix per [quickstart.md §1.3](./quickstart.md). Document the PASS/FAIL count in the PR description (SC-001 + SC-002). Not gated by CI.

**Checkpoint**: User Story 1 fully functional. The unit tests (T004) and integration test (T005) lock in the sanitizer's contract; the manual reproducer (T006) confirms the production failure mode is closed.

---

## Phase 4: User Story 2 — Other JSONB-bound writes are equally protected (Priority: P2)

**Goal**: The fix is general — applies to all five JSONB columns, not just `agent_tool_calls.output_json`.

**Independent Test**: A grep verifying the sanitizer is imported at exactly one place; plus the unit tests from T004 cover the sanitizer's general-purpose contract.

### Implementation for User Story 2

- [X] T007 [US2] No code change. Verified by inspection: `_SanitizedJSON` wraps `JSONType`, which all five JSONB columns use via `mapped_column(JSONType, ...)`. The integration test (T005) additionally exercises a second JSONB column (`agent_runs.metadata_json`) to lock in the breadth.

### Tests for User Story 2

- [X] T008 [P] [US2] SC-006 grep verified. Output: only one **import** site (`models.py:36`); other matches are inside docstrings/code-comments (acceptable; not import sites). Documented for the PR.

- [X] T009 [P] [US2] `test_handles_pydantic_model_dump_output` landed inside `test_jsonb_sanitizer.py` (constructed a `BaseModel` with a `float | None` field set to NaN, called `model_dump()`, confirmed Pydantic preserves the NaN, then ran through the sanitizer and confirmed `None` in the output).

**Checkpoint**: US2 verified. The fix's breadth is confirmed both by static-analysis grep and by exercising the Pydantic upstream path.

---

## Phase 5: User Story 3 — A regression test prevents this class of bug from coming back (Priority: P1)

**Goal**: A future contributor cannot silently re-introduce the bug. The CI gate is the regression suite from Phase 3 (T004 + T005).

**Independent Test**: Verify the regression suite fails on a hypothetical revert per [quickstart.md §3](./quickstart.md).

### Verification for User Story 3

- [X] T010 [US3] **Verified during implementation.** Procedure: moved `sanitize.py` aside (`mv` to `/tmp`), reverted `models.py` to the pre-fix line `JSONType = JSONB().with_variant(JSON(), "sqlite")` (also removed the `from .sanitize import sanitize_for_jsonb` import). Result: the unit test file fails to even import (`ModuleNotFoundError: discogs_agent.persistence.sanitize`); the integration tests fail 2 of 3 cases (`assert not _has_any_nan(...)` raises with the un-sanitized NaN/Infinity values intact in the fetched JSON). The clean-data integration test correctly still passes (sanitization is a no-op on clean data — exactly what's expected). Restored both files; all 21 tests green again. SC-003 satisfied. Implementation note: `git stash` doesn't stage untracked files like `sanitize.py` — had to do the revert manually.

**Checkpoint**: US3 verified. The regression suite is load-bearing.

---

## Phase 6: Polish & Cross-cutting

- [X] T011 [P] Full agent test suite: **179 passed, 2 skipped** (`pytest tests/`). No regressions. Pre-010 was ~158 (post-009); +21 from 010.

- [X] T012 [P] `mypy --strict src/discogs_agent/persistence/sanitize.py src/discogs_agent/persistence/models.py`: **Success: no issues found in 2 source files**.

- [X] T013 [P] `ruff format` reformatted 2 test files (minor whitespace). `ruff check` on all 4 files: **All checks passed!**.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup, Foundational**: empty.
- **Phase 3 (US1)**: T001 first (sanitizer), T002 depends on T001 (uses `sanitize_for_jsonb`), T003 independent (contract amendment), T004 depends on T001, T005 depends on T001+T002, T006 depends on T002.
- **Phase 4 (US2)**: T007 verification-only (no code), T008 verification-only (grep), T009 extends T004.
- **Phase 5 (US3)**: T010 depends on all earlier tasks being implemented.
- **Phase 6 (Polish)**: depends on all implementation tasks.

### User Story Dependencies

- **US1 (P1)**: foundational — establishes the fix and its core regression tests.
- **US2 (P2)**: depends on US1 implementation; no new code of its own.
- **US3 (P1)**: depends on US1 implementation; the regression test IS the US1 deliverable.

### Within Each User Story

- T001 first (sanitizer is self-contained).
- T002, T003 in parallel after T001.
- T004 after T001; T005 after T002; both can run in parallel with each other.
- T006 last in US1 (manual smoke).

### Parallel Opportunities

- **Phase 3**: T002/T003 in parallel after T001. T004/T005 in parallel after their respective deps.
- **Phase 4**: T008/T009 in parallel.
- **Phase 6**: all polish tasks marked [P] in parallel.

---

## Parallel Example: User Story 1

```bash
# After T001 lands, parallel:
Task: "Modify models.py to wrap JSONType with _SanitizedJSON TypeDecorator"
Task: "Apply contract amendment to 004/contracts/postgres-schema.md §7"

# After T002 lands, tests in parallel:
Task: "Unit test for sanitize_for_jsonb in tests/unit/test_jsonb_sanitizer.py"
Task: "Integration test through ToolCallRepo in tests/integration/test_jsonb_nan_persistence.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 3 (US1) — sanitizer + chokepoint + contract amendment + unit + integration tests.
2. **STOP and VALIDATE**:
   - `pytest agent/tests/unit/test_jsonb_sanitizer.py agent/tests/integration/test_jsonb_nan_persistence.py` green.
   - Manual reproducer ([quickstart.md §1.3](./quickstart.md)): ≥9/10 PASS, 0 InvalidTextRepresentation in logs.
3. The bug is closed. Demo path is unblocked.

### Incremental Delivery

The fix is small enough that incremental delivery is mostly cosmetic. A reasonable cut:

1. **Increment 1 — Sanitizer + chokepoint** (T001+T002): the producer change.
2. **Increment 2 — Contract** (T003): updates `004/contracts/postgres-schema.md`.
3. **Increment 3 — Tests** (T004+T005+T009): locks in the behavior.
4. **Increment 4 — Polish** (T010+T011+T012+T013): green gates + manual smoke.

For PR purposes a single commit is fine.

### Parallel Team Strategy

With one developer (typical for this size):

1. T001.
2. T002, T003 in any order.
3. T004, T005 in parallel after T001 / T002.
4. T006, T008, T009, T010 at the end.
5. Polish closes out.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks in the same phase.
- `[Story]` label maps task to a specific user story for traceability.
- Tests here are explicitly mandated by FR-010 and FR-011 — they are not optional.
- Constitution VII.c is the disciplinary analog. The integration test (T005) is the mechanical enforcement of the boundary discipline.
- 13 tasks total across 6 phases. Setup: 0. Foundational: 0. US1: 6. US2: 3. US3: 1. Polish: 3.
