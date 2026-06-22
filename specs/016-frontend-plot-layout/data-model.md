# Phase 1 Data Model: Frontend Plot Layout & ID Copy

This feature is presentational. It introduces **no** new persisted
entities, no API fields, and no schema changes. The only "data" involved
is pre-existing UI state plus one piece of ephemeral, component-local
state for the copy confirmation.

## Existing entities consumed (unchanged)

### RunMetadata (frontend type, `frontend/src/api/types.ts`)

Already delivered by the agent `/query` response and rendered today by
`RunMetadata.tsx`. The fields this feature reads:

| Field            | Type             | Use in this feature                                  |
|------------------|------------------|------------------------------------------------------|
| `run_id`         | `string`         | **Full** value copied to clipboard (US3, FR-007)     |
| `thread_id`      | `string`         | **Full** value copied to clipboard (US3, FR-008)     |
| `status`         | `ResponseStatus` | unchanged (existing status badge)                    |
| `complexity`     | `string \| null` | unchanged                                            |
| `selected_model` | `string \| null` | unchanged                                            |

The badge continues to **display** a truncated id (`truncateId`, 6 chars +
ellipsis) while the copy action copies the **untruncated** value — this
display/copy split is the one behavioral invariant US3 adds.

## New component-local state

### Copy confirmation state (ephemeral, `RunMetadata.tsx`)

Not persisted, not in the app reducer, not in localStorage — purely
transient UI feedback.

| State              | Type                          | Lifecycle                                                                 |
|--------------------|-------------------------------|---------------------------------------------------------------------------|
| `copied`           | `null \| "run" \| "thread"`   | set on a successful clipboard write; auto-cleared after ~1.5s; identifies which id was just copied so only that control shows the confirmation |

Transitions:
- `null` → `"run"` / `"thread"` — on successful `writeText` for that id.
- `"run"`/`"thread"` → `null` — after the confirmation timeout, or when
  the other id is copied (only one confirmation shown at a time).
- On clipboard **failure** the state stays `null` (FR-010: no false
  success).

## Layout configuration (not data)

The US1 rebalance is a Tailwind grid-template-columns class change in
`App.tsx`. It is a static presentation constant, not state and not
runtime configuration — there is no entity to model. The invariant it
must preserve (result column wider than conversation; conversation keeps a
usable minimum width) is captured in `contracts/frontend-layout.md`.

## Chart legend (not frontend data)

The legend-below-plot behavior (US2) is a property of the agent-generated
Plotly figure, set in the code-generation prompt. The frontend stores and
models nothing about it; the chart remains an opaque HTML artifact
referenced by URL (`ChartArtifact`, unchanged). See
`contracts/chart-legend.md`.
