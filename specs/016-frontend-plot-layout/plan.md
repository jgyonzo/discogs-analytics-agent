# Implementation Plan: Frontend Plot Layout & ID Copy

**Branch**: `016-frontend-plot-layout` | **Date**: 2026-06-22 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/016-frontend-plot-layout/spec.md`

## Summary

Three small polish changes that span **two components**:

1. **Rebalance the wide layout** (frontend) so the result/chart region is
   the widest of the three columns and the conversation is narrower —
   `App.tsx` grid template only.
2. **Legends below the plot** (agent) — the chart is opaque Plotly HTML
   the frontend renders in a sandboxed iframe, so legend orientation is
   set where the chart is generated: a one-line `fig.update_layout(...)`
   added to the canonical code shape in `code_generator.md`.
3. **Copy buttons for run id and thread id** (frontend) — augment the
   existing `RunMetadata` badges with a copy affordance that writes the
   full (untruncated) id to the clipboard with a transient "copied"
   confirmation, keyboard-operable and a11y-labeled.

No API, persistence, schema, or DuckDB-contract changes. No new runtime
dependencies (`lucide-react` and `clsx` are already present). The iframe
sandbox posture is unchanged.

## Technical Context

**Language/Version**: TypeScript 5.7 / React 18.3 (frontend); Python 3.12 (agent prompt asset)
**Primary Dependencies**: Vite 5, Tailwind 3.4, clsx, lucide-react (frontend); Plotly Express via the agent's generated code shape (agent)
**Storage**: N/A — no persistence touched
**Testing**: Vitest + Testing Library + jsdom (frontend, `frontend/tests/`); existing agent prompt/contract tests (agent)
**Target Platform**: Browser SPA served by the Vite dev-server container; agent service container
**Project Type**: Web SPA (third monorepo component) + agent service
**Performance Goals**: N/A — purely presentational; no new network or compute paths
**Constraints**: Frontend never reads DuckDB/Postgres/ETL and never executes agent-generated code; chart stays opaque HTML inside `sandbox="allow-scripts"` iframe (no `allow-same-origin`); clipboard write must degrade gracefully when unavailable/denied
**Scale/Scope**: ~2 frontend files (`App.tsx`, `RunMetadata.tsx`) + their tests; 1 agent prompt file (`code_generator.md`) + its contract; Demo-Day-scale single-user UI

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Components touched**: **frontend** (US1 layout, US3 copy buttons) and
**agent** (US2 legend placement). Per the Development-Workflow plan gate,
both are named here so the right constraints apply.

- **Principle VI (Two Components, One Contract)** — PASS. The frontend
  change touches only frontend files; the agent change touches only the
  agent's prompt asset. No cross-component imports introduced. The
  published DuckDB contract is untouched (no schema change ⇒ not a
  cross-component contract change). The frontend continues to consume
  only the already-shipped `/query` payload (run_id, thread_id already
  delivered). The 008-era third-component allowance stands.
- **Principle VII(b) (Prompt-authoring discipline)** — PASS. The only
  prompt edit is a chart-**styling** instruction (legend orientation) in
  the canonical code shape. It does not describe tables, grains, columns,
  sample values, or what the catalog contains, and it does not duplicate
  anything `{schema_context_block}` renders. VII(b) governs schema prose;
  legend layout is outside its scope.
- **Principle VII(a) (Configuration sources)** — N/A / PASS. No model
  ids, paths, timeouts, budgets, or flags are introduced. The grid ratio
  and legend orientation are presentation constants, not runtime config
  of the kind VII(a) governs (they are not operator-tunable behavior).
- **Principle VII(c) (Read-only runtime mechanics)** — N/A. No change to
  read-only mounts, spill, or filesystem mechanics.
- **Principles I–V** — N/A. No data-layer, ETL, grain, counting, or
  analytics-surface changes.
- **Security posture** — PASS. The iframe sandbox flags are unchanged;
  the frontend still treats the chart as opaque and does not read into
  it. Clipboard access is a standard, user-initiated browser API.

**Result**: No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/016-frontend-plot-layout/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── frontend-layout.md      # grid rebalance + copy-button UI contract
│   └── chart-legend.md         # agent code-shape legend amendment
├── checklists/
│   └── requirements.md  # created by /speckit-specify
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── App.tsx                       # US1: grid-template-columns rebalance
│   └── components/
│       └── RunMetadata.tsx           # US3: per-id copy button + copied state
└── tests/
    └── components/
        └── RunMetadata.test.tsx      # extend: copy full id, confirmation, a11y, graceful failure

agent/
└── src/discogs_agent/prompts/
    └── code_generator.md             # US2: legend-below-plot in canonical code shape
```

**Structure Decision**: Reuse the existing three-component monorepo layout
(`etl/`, `agent/`, `frontend/`) from 008. This feature adds no new
directories, files, or dependencies — it edits two existing frontend
files (plus one test file) and one agent prompt asset. The split by
component matches the Constitution Check: layout + copy live in
`frontend/`, legend lives in `agent/`.

## Complexity Tracking

> No Constitution Check violations. Section intentionally empty.
