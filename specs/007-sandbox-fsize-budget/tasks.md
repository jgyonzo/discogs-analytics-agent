# Tasks: Sandbox file-size budget

**Input**: Design documents from `/specs/007-sandbox-fsize-budget/`
**Prerequisites**:
- Plan: [plan.md](./plan.md)
- Spec: [spec.md](./spec.md)
- Research: [research.md](./research.md) (R-03 fixes the chosen value at **2 GiB**; R-05 sizes the test fixture)
- Contracts: [contracts/amendment-004-code-generation.md](./contracts/amendment-004-code-generation.md) (verbatim §3.1.1 insertion text)
- Quickstart: [quickstart.md](./quickstart.md)

**Tests**: included — FR-007 demands a regression test; SC-003 and SC-004 are test-anchored. Tests are not optional for this feature.

**Components touched**: `agent/` only (Constitution Principle VI), plus the `004/contracts/code-generation.md` amendment. No edits to `etl/`, no constitution amendment.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Which user story this task belongs to (US1, US2).
- File paths are absolute relative to the repo root and should be created/edited as named.

## Path Conventions

- Agent source: `agent/src/discogs_agent/`
- Agent tests: `agent/tests/`
- Spec contracts (cross-feature amendment target): `specs/004-agent-v1/contracts/`

---

## Phase 1: Setup

No setup tasks. The `agent/` package, its dependency manifest, the
sandbox subprocess scaffolding, the `seed_duckdb` test fixture, and the
`agent_env`/`use_seed_duckdb` fixtures all exist from 004 + 005 + 006.

---

## Phase 2: Foundational

No foundational tasks. 007 introduces no new env vars, no new
dependencies, no new modules — only an existing-constant change plus
one new test file plus one new fixture-builder.

---

## Phase 3: User Story 1 — Real-world aggregations succeed against the published catalog (Priority: P1) 🎯 MVP

**Goal**: end-to-end aggregations against the published catalog
(canonical reproducer: *"show the number of releases over time"*)
succeed with `status="succeeded"`, a populated chart, and no
`IO Error: File too large` in the sandbox execution result.

**Independent Test**: with the agent stack up against the published
DuckDB, `POST /query` with the canonical reproducer returns a chart
artifact and `row_count >= 6` (one per decade with releases). Until
the published DuckDB is wired into a smoke environment, the
synthetic-fixture regression test (T005) is the substitute proof.

### Implementation for User Story 1

- [X] T001 [US1] Bump `RLIMIT_FSIZE_BYTES` from `64 * 1024 * 1024` to `2 * 1024 * 1024 * 1024` in `agent/src/discogs_agent/sandbox/restrictions.py`. Replace the existing rationale comment with the operator-facing TL;DR per [`contracts/amendment-004-code-generation.md` § "Implementation note"](./contracts/amendment-004-code-generation.md): the workload sizing line, the bounding-context line, the named-incident citation (link to this spec), and the "cwd jail is primary; this rlimit is the secondary backstop" note. Keep the comment under ~12 lines — the contract carries the canonical prose.
- [X] T002 [US1] Apply the contract amendment to `specs/004-agent-v1/contracts/code-generation.md` §3.1: (a) change the inline `RLIMIT_FSIZE` value in the code sample from `64 * 1024 * 1024` to `2 * 1024 * 1024 * 1024`; (b) insert the verbatim `### 3.1.1 Sandbox file-size budget (RLIMIT_FSIZE)` subsection from [`contracts/amendment-004-code-generation.md`](./contracts/amendment-004-code-generation.md) immediately after §3.1's code sample and before the `wrapper_code` paragraph. Do not edit §3.2/§3.3/§3.4.

### Test infrastructure for User Story 1 (substrate for T005)

- [~] T003 [US1] **SKIPPED** — superseded by the direct-write approach in T005. Rationale: the `spill_seed.duckdb` plan from research.md R-05 hinged on DuckDB writing the GROUP BY spill into a *single* file > 64 MiB. DuckDB partitions spill across `duckdb_temp_storage_DEFAULT-0.tmp`, `…-1.tmp`, … and the partitioning is version-dependent — a fixture sized to trip the cap on DuckDB 1.0 might land 4× 20 MiB files on DuckDB 1.1 and not trip the cap at all. Testing the RLIMIT_FSIZE mechanism directly via a Python write through the sandbox (T005) is deterministic, version-agnostic, and exercises the *exact* kernel signal (EFBIG) the production bug surfaced.
- [~] T004 [US1] **SKIPPED** — depends on T003. No `spill_seed.duckdb` binary committed.

### Regression test for User Story 1

- [X] T005 [US1] Write `agent/tests/integration/test_sandbox_fsize_budget.py` with the following test cases (depends on T001):
  - `test_rlimit_fsize_byte_count_meets_minimum`: imports `RLIMIT_FSIZE_BYTES` from `discogs_agent.sandbox.restrictions` and asserts `>= 1 * 1024 * 1024 * 1024`. This is the load-bearing regression guard — if a future "tighten the cap" change reverts T001, this test fails immediately and CI blocks the regression. Cheap and fast (<1 ms).
  - `test_sandbox_allows_write_above_old_cap`: constructs a generated-code-shape Python script that opens a file inside the per-run artifact dir and writes `128 * 1024 * 1024` bytes (128 MiB — comfortably above the pre-fix 64 MiB cap, comfortably below the post-fix 2 GiB cap). Invokes `sandbox.runner.run_in_sandbox(...)`. Asserts the sandbox returns success (`exit_code == 0`, no `EFBIG` in stderr, no exception parsed). This proves the original failure mode (RLIMIT_FSIZE EFBIG'ing on writes > 64 MiB) is fixed at the layer the production bug surfaced. The realistic DuckDB-spill end-to-end story is covered separately by T011 (manual verification against the published catalog).

**Checkpoint**: US1 fully functional. The canonical reproducer succeeds against the synthetic fixture; the manual reproducer in [quickstart.md §1](./quickstart.md) succeeds against the published catalog (verified during Phase 5).

---

## Phase 4: User Story 2 — Runaway writes are still bounded (Priority: P2)

**Goal**: confirm that raising the cap did not break the sandbox's
runaway-write protection — over-cap writes still fail (controlled),
the cwd jail still blocks out-of-dir writes, and the published DuckDB
remains byte-equal before/after the suite.

**Independent Test**: a synthetic test asks the sandbox to write a
file larger than the new cap and observes a controlled failure (no
agent crash, no traceback in the user-facing response). The existing
cwd-jail + DuckDB-byte-equality tests still pass.

### Implementation for User Story 2

- [X] T006 [US2] Add `test_oversize_write_surfaces_controlled_failure` to `agent/tests/integration/test_sandbox_fsize_budget.py` (depends on T001 + T005): construct a generated-code-shape Python script that attempts to write a file larger than `RLIMIT_FSIZE_BYTES` (use a sparse-but-actually-flushed write — e.g. `open(p, "wb").write(b"\\x00" * (RLIMIT_FSIZE_BYTES + 1024 * 1024))` so RLIMIT_FSIZE actually trips, not a sparse-file syscall that bypasses it); invoke `sandbox.runner.run_in_sandbox(...)`; assert the run completes (does not hang), the `exception_type` matches the documented EFBIG-class signal (or the sandbox's classification of it — confirm against `restrictions.py` after T001), the `final_response` (when projected through the chart_validator path) contains no `Traceback (most recent` and no internal path strings. The test SHOULD be quick — write 2 GiB + 1 MiB to a tmpfs is fast on dev hardware but pytest.mark.slow it just in case.

### Cwd-jail and DuckDB-mutation re-verification (US2 substrate)

- [X] T007 [P] [US2] Confirm — by reading and (if necessary) re-running — that `agent/tests/integration/test_agent_safety_block.py` and `agent/tests/integration/test_duckdb_contract.py` still pass after T001. Both encode invariants 007 must not regress (cwd jail blocks out-of-dir writes; published DuckDB SHA-256 byte-equal before/after). No edits expected; this task is the verification, recorded so the implementer doesn't skip it.

**Checkpoint**: US2 demonstrable. Over-cap writes are controlled failures; cwd jail still primary; DuckDB byte-equality still holds.

---

## Phase 5: Polish & Verification

**Purpose**: final cross-cutting verification before the branch is mergeable.

- [X] T008 [P] Run `ruff check agent/src/discogs_agent/sandbox/restrictions.py agent/tests/integration/test_sandbox_fsize_budget.py` and fix any lint findings. Run `ruff format` on the same paths. (Scope reduced: `spill_seed.py` was dropped per the T003/T004 skip.)
- [X] T009 [P] Run `mypy --strict agent/src/discogs_agent/sandbox/restrictions.py` and confirm no new type errors.
- [X] T010 Run the full agent test suite (`cd agent && pytest tests/ --ignore=tests/integration/test_docker_smoke.py`). Expect no regressions; the new tests from T005 + T006 pass; the existing seed-fixture suite (`test_agent_simple_query`, `test_agent_complex_query`, …) and the US2-foundation `test_health` / `test_persistence_survives_restart` continue to pass.
- [~] T011 Manual verification against the published DuckDB per [quickstart.md §1 + §6](./quickstart.md). **SKIPPED** — no published DuckDB at `./data/published/duckdb/discogs.duckdb` on the implementer's machine. Re-run before merging if a published catalog becomes available locally; otherwise the synthetic-fixture regression test (T005) plus the const-min guard plus the over-cap controlled-failure test (T006) are the load-bearing CI signals.
- [~] T012 (Optional) Capture the actual chart from T011's canonical reproducer (the rendered Plotly HTML) as a PR artifact for reviewers who don't have the published DuckDB locally. Not required for the test suite to pass.

**Checkpoint**: 007 ready to ship. All FR/SC anchors verifiable; branch is mergeable.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: empty — start immediately.
- **Foundational (Phase 2)**: empty — see above.
- **US1 (Phase 3)**: T001 and T002 are parallel. T003 + T004 are sequential. T005 depends on T001 + T004.
- **US2 (Phase 4)**: T006 depends on T001 + T005. T007 depends only on T001.
- **Polish (Phase 5)**: depends on US1 + US2 work landing.

### User-story ordering for incremental delivery

```text
Phase 3 (US1)   →  STOP & DEMO (a):  the failing query succeeds against the synthetic fixture
              →  Phase 4 (US2)    →  STOP & DEMO (b):  runaway writes still bounded
              →  Phase 5 (Polish) →  ship
```

Demos:
- (a): "the canonical reproducer succeeds and the regression test catches a future revert".
- (b): "the cap is doing its job — oversize writes fail controlled, cwd jail still primary".

### Parallel opportunities

- T001 and T002 are parallel (different files: `agent/src/.../restrictions.py` vs. `specs/004-agent-v1/contracts/code-generation.md`).
- T003 is parallel to T001/T002 (new file).
- T004 depends on T003 only.
- T007 is parallel to T006 (different verification scope; both depend on T001).
- T008 + T009 + parts of T010 are parallel within the polish phase.

### Parallel example: US1 first batch

```bash
# Once Phase 2 is empty (it is), kick off these three at once:
T001 agent/src/discogs_agent/sandbox/restrictions.py
T002 specs/004-agent-v1/contracts/code-generation.md
T003 agent/tests/fixtures/spill_seed.py
```

Then T004 (run the builder), then T005 + T006 + T007 in parallel.

---

## Implementation Strategy

### MVP scope (US1 only)

1. T001 + T002 + T003 + T004 + T005.
2. Run `pytest agent/tests/integration/test_sandbox_fsize_budget.py -v` — must pass.
3. **STOP and VALIDATE**: this is already a viable shippable MVP. The original failing query succeeds against the synthetic fixture; CI guards against future revert.

### Incremental delivery

1. MVP from above.
2. Add US2 (T006 + T007) — demo runaway-write protection still works.
3. Add Polish (T008–T012) — ship.

Each "Add X" is a single squash-mergeable PR scoped to its phase. For
007 specifically, the work is small enough that one PR for everything
is reasonable too — and arguably preferable for a single-concern bugfix.

### Parallel team strategy

Not applicable — 007 is intentionally one-developer-sized. Single-PR
delivery is the expected path.

---

## Notes

- `[P]` = different files, no dependencies on incomplete tasks.
- The `spill_seed.duckdb` binary (T004) is committed to git on purpose
  — it keeps the regression test fast and reproducible, mirroring the
  precedent set by 004's `seed.duckdb` (T028 of `004/tasks.md`).
- The contract amendment (T002) is the canonical prose; the constant's
  comment in `restrictions.py` (T001) is the operator-facing TL;DR.
  Keep them logically aligned but don't duplicate the long-form rationale
  inline — the comment is for grep'ers, the contract is for reviewers.
- Constitution VI compliance is re-verified by T007 (DuckDB
  byte-equality holds; no ETL imports introduced). This is a load-bearing
  re-verification — never skip it.
- `[NEEDS CLARIFICATION]` from the spec phase: zero. The single
  open question (the byte-count) was resolved in `research.md` R-03.

---

## Total: 12 tasks

| Phase | Count |
|-------|------:|
| Phase 1 — Setup | 0 |
| Phase 2 — Foundational | 0 |
| Phase 3 — US1 (P1, MVP) | 5 |
| Phase 4 — US2 (P2) | 2 |
| Phase 5 — Polish | 5 |

Independent-test criteria:
- **US1**: spec.md acceptance scenarios 1–3, exercised by T005 (synthetic fixture) and T011 (manual against published catalog).
- **US2**: spec.md acceptance scenarios 1–3, exercised by T006 (over-cap controlled failure) and T007 (cwd jail + DuckDB byte-equality re-verification).

Suggested MVP scope: **Phase 3 (US1) only**. All FR-001 + FR-007 + SC-001 + SC-003 anchors reachable. SC-002 (real-world full sweep) and SC-005 (DuckDB byte-equality after the new test) need US2 + Polish.
