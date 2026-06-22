# Tasks: Frontend Plot Layout & ID Copy

**Input**: Design documents from `/specs/016-frontend-plot-layout/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included for US3 only (clipboard/copy behavior) — specified in
`research.md` R4 and matching the existing `frontend/tests/` conventions.
US1 (layout) and US2 (prompt) are verified via typecheck + the manual
`quickstart.md`, per the plan.

**Organization**: Tasks are grouped by user story. The three stories are
**fully independent** — each touches a different file (`App.tsx`,
`code_generator.md`, `RunMetadata.tsx`) — so all three phases can run in
parallel after setup.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Three-component monorepo (`etl/`, `agent/`, `frontend/`). Frontend work
under `frontend/src/` and `frontend/tests/`; agent prompt asset under
`agent/src/discogs_agent/prompts/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the working environment; no new deps or scaffolding
are introduced by this feature.

- [X] T001 Confirm `frontend/` deps install and the baseline suite is green before edits: from `frontend/`, run `npm install` then `npm run typecheck && npm run test`. Confirm `lucide-react` and `clsx` are present in `frontend/package.json` (no new dependency is needed for the copy button).

**Checkpoint**: Baseline green — the three user stories can proceed in parallel.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. This feature adds no shared models, API, or
infrastructure that the stories depend on. Intentionally empty.

---

## Phase 3: User Story 1 - More room for the chart, less for the conversation (Priority: P1) 🎯 MVP

**Goal**: On the wide layout, make the result/chart column the widest and
the conversation a bit narrower while keeping the conversation usable;
mobile stacking unchanged.

**Independent Test**: On a wide viewport, run a question and confirm the
result column is wider than the conversation, the chart uses the extra
width, the conversation stays readable/usable, and narrow viewports still
stack (per `quickstart.md` US1).

- [X] T002 [P] [US1] In `frontend/src/App.tsx`, change the `<main>` grid template from `lg:grid-cols-[20rem_1fr_1fr]` so the result column is the dominant flexible track and the conversation has a usable minimum width — e.g. `lg:grid-cols-[18rem_minmax(22rem,0.9fr)_1.6fr]`. Keep `grid-cols-1` (single-column stacking) for narrow viewports unchanged. Satisfies contract `frontend-layout.md` L-1…L-5 (FR-001, FR-002, FR-003, FR-004).
- [X] T003 [US1] Verify US1: from `frontend/` run `npm run typecheck`, then follow `quickstart.md` US1 — confirm on a wide viewport the result column is wider than the conversation, the chart crops less, the conversation/input stay usable (SC-001, SC-002, SC-006), and below the `lg` breakpoint the regions stack vertically (FR-003).

**Checkpoint**: US1 independently demoable — wider chart, usable conversation.

---

## Phase 4: User Story 2 - Chart legends always sit below the plot (Priority: P2)

**Goal**: Every generated chart that has a legend places it horizontally
below the plot rather than to the side.

**Independent Test**: Run a question whose chart has a legend and confirm
the legend renders horizontally beneath the plot; a single-series chart is
unaffected (per `quickstart.md` US2).

- [X] T004 [P] [US2] In `agent/src/discogs_agent/prompts/code_generator.md`, amend the "Required code shape" block to add a legend-layout call immediately after `fig = px.<chart_kind>(df, ...)` and before `fig.write_html(...)`: `fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5))`. Add a one-line note stating the intent ("place any legend horizontally below the plot") so the LLM keeps the call when adapting the template. Keep the edit confined to the styling/code-shape region — do NOT add any table/grain/column/sample-value prose (Principle VII(b)). Satisfies contract `chart-legend.md` G-1…G-3 (FR-005, FR-006).
- [X] T005 [US2] Verify US2 per `quickstart.md` US2: run a legend-bearing question and confirm the legend is horizontal and below the plot (SC-003); run a single-series question and confirm no empty legend strip or broken layout (FR-006). Spot-check across a few curated questions (LLM-generated; strong default, not a hard invariant).

**Checkpoint**: US2 independently demoable — consistent bottom legends.

---

## Phase 5: User Story 3 - Copy the run id and thread id with one click (Priority: P3)

**Goal**: Add a one-click copy control to the run-id and thread-id badges
that copies the full (untruncated) id with visible confirmation,
keyboard-operable and a11y-labeled, degrading gracefully on failure.

**Independent Test**: Run a question, click copy on the run badge, confirm
the full run id is on the clipboard with a confirmation; repeat for thread
id; keyboard-activate; and a denied clipboard shows no false success (per
`quickstart.md` US3).

- [X] T006 [P] [US3] In `frontend/src/components/RunMetadata.tsx`, add a copy control to the `run` and `thread` badges. Implementation per contract `frontend-layout.md` C-1…C-7 and `data-model.md`: render a real `<button>` (use `lucide-react` `Copy`/`Check` icons + `clsx`); on click call `navigator.clipboard.writeText(<full id>)` with the **untruncated** id (not the `truncateId` display value); add ephemeral `copied: null | "run" | "thread"` state that shows a transient (~1.5s) check confirmation on the activated control only; wrap the write in try/catch so a rejected/unavailable clipboard sets no success state and throws nothing (FR-010); give each button an `aria-label` ("Copy run id" / "Copy thread id") and convey the copied state to assistive tech; preserve existing `data-testid="run-metadata-run-id"` / `"run-metadata-thread-id"` and add `data-testid="copy-run-id"` / `"copy-thread-id"`. The copy control renders only as part of the existing per-id badge (FR-007, FR-008, FR-009, FR-011, FR-012, SC-004, SC-005).
- [X] T007 [US3] In `frontend/tests/components/RunMetadata.test.tsx`, extend the suite (mock `navigator.clipboard.writeText`): (a) clicking the run copy control calls `writeText` with the **full** untruncated `run_id` (and thread control with full `thread_id`) — SC-004; (b) a "copied" confirmation (check icon / state) appears after a successful copy — SC-005; (c) each copy control has an accessible name (`getByRole("button", { name: /copy run id/i })`) — FR-011; (d) when `writeText` rejects, no success confirmation appears and nothing throws — FR-010. Then run `npm run test` and `npm run typecheck` from `frontend/`.

**Checkpoint**: US3 independently demoable and unit-tested — full-id copy with confirmation.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across the whole change.

- [X] T008 From `frontend/`, run the full gate `npm run typecheck && npm run test` and confirm the entire suite (existing + new US3 tests) is green and no regressions in `full-flow`/`multi-turn` integration tests.
- [X] T009 [P] Walk the complete `quickstart.md` (US1 + US2 + US3) end-to-end against the running local stack to confirm the three improvements work together and the iframe sandbox / opaque-chart posture is unchanged.

---

## Dependencies & Execution Order

- **Setup (Phase 1, T001)** → must complete first (establishes green baseline).
- **Phase 2 (Foundational)** → empty; nothing blocks the stories.
- **User Stories (Phases 3–5)** → all independent; T002 (US1), T004 (US2),
  and T006 (US3) touch three different files and may be done in any order
  or concurrently. Each story's verify task depends only on its own
  implementation task (T003←T002, T005←T004, T007←T006).
- **Polish (Phase 6)** → after the stories you intend to ship are done.

### Story independence

| Story | File(s) touched | Component |
|-------|-----------------|-----------|
| US1   | `frontend/src/App.tsx` | frontend |
| US2   | `agent/src/discogs_agent/prompts/code_generator.md` | agent |
| US3   | `frontend/src/components/RunMetadata.tsx`, `frontend/tests/components/RunMetadata.test.tsx` | frontend |

No two stories share a file ⇒ no inter-story merge conflicts.

## Parallel Execution Examples

After T001, the three implementation tasks can run in parallel:

```text
T002 [P] [US1]  App.tsx grid rebalance
T004 [P] [US2]  code_generator.md legend layout
T006 [P] [US3]  RunMetadata.tsx copy controls
```

## Implementation Strategy

- **MVP = US1 alone** (P1): the headline "bigger chart" win; ships
  independently with just T001 → T002 → T003.
- **Incremental**: add US2 (bottom legends) and US3 (copy buttons) in any
  order afterward; each is a self-contained increment with its own verify
  task. Close with Phase 6 once the desired set is in.

## Notes

- No new runtime dependencies; no API/persistence/schema/DuckDB-contract
  changes; iframe sandbox flags unchanged.
- Per the project's commit-splitting preference, consider committing US1,
  US2, and US3 as separate commits (frontend layout / agent prompt /
  frontend copy) since they are independent concerns across two components.
