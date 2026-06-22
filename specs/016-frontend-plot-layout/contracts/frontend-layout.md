# Contract: Frontend Layout Rebalance & ID Copy Controls

Scope: `frontend/` only. Consumes the already-shipped agent `/query`
payload; adds no API fields. No change to the iframe sandbox.

## 1. Wide-layout column rebalance (US1)

**Subject**: `frontend/src/App.tsx`, the `<main>` grid.

**Today**: `lg:grid-cols-[20rem_1fr_1fr]` — three columns
(suggested-questions rail, conversation, result) where conversation and
result share width equally.

**Required invariants** (the contract pins behavior, not exact pixels):

- **L-1**: On the wide (`lg`) layout the **result** column MUST be
  allocated more horizontal space than the **conversation** column.
  (FR-001, SC-001)
- **L-2**: The conversation column MUST retain a usable minimum width so
  its history stays readable and the `QueryInput` stays fully usable —
  e.g. enforced with a `minmax(<floor>, …)` track. (FR-002, SC-006)
- **L-3**: The suggested-questions rail keeps roughly its current narrow
  width (small reduction permitted, not a removal). (Assumption: space
  split)
- **L-4**: On narrow viewports the layout MUST remain single-column
  stacked exactly as today (`grid-cols-1`); the rebalance applies only to
  the `lg` breakpoint. (FR-003)
- **L-5**: The result column being wider MUST let the chart iframe use
  the extra width (the iframe is already `w-full`); no change to the
  iframe element's sandbox or dimensions semantics beyond width. (FR-004,
  SC-002)

**Reference implementation** (illustrative, not normative):
`lg:grid-cols-[18rem_minmax(22rem,0.9fr)_1.6fr]`.

**Out of scope**: resizable splitters, collapsible panels, persisted
layout preferences.

## 2. Run-id / thread-id copy controls (US3)

**Subject**: `frontend/src/components/RunMetadata.tsx`, the `run` and
`thread` badges.

- **C-1**: Each of the run-id and thread-id badges MUST expose a copy
  control (a real `<button>`). (FR-007, FR-008)
- **C-2**: Activating a copy control MUST write the **full, untruncated**
  id to the clipboard via `navigator.clipboard.writeText`, even though the
  badge displays the truncated form. (FR-007, FR-008, SC-004)
- **C-3**: On a successful copy the UI MUST show a brief, clear
  confirmation local to the activated control (e.g. icon swap to a check
  for ~1.5s). Only one confirmation is shown at a time. (FR-009, SC-005)
- **C-4**: If the clipboard write rejects or is unavailable, the UI MUST
  NOT show a success confirmation and MUST NOT throw/crash. The wrapping
  call MUST catch the rejection. (FR-010)
- **C-5**: Each copy control MUST have an accessible name (e.g.
  `aria-label="Copy run id"` / `"Copy thread id"`), MUST be
  keyboard-focusable and activatable, and the copied state MUST be
  conveyed to assistive technology. (FR-011)
- **C-6**: A copy control MUST render only when its id is present — it is
  part of the per-id badge, which already renders conditionally; no orphan
  control when run_id or thread_id is absent. (FR-012)
- **C-7**: Existing `data-testid` hooks (`run-metadata-run-id`,
  `run-metadata-thread-id`) MUST be preserved; the copy control SHOULD add
  its own testable hook (e.g. `data-testid="copy-run-id"` /
  `"copy-thread-id"`) for the new tests.

**Out of scope**: copying other metadata fields (status/model/complexity),
a global toast system, copy-on-badge-click.

## 3. Non-goals / preserved invariants

- No new runtime dependency (use existing `lucide-react`, `clsx`).
- No change to `frontend/src/api/types.ts`, the API client, or the
  reducer/localStorage shape.
- Chart iframe stays `sandbox="allow-scripts"` (no `allow-same-origin`);
  the frontend never reads into the chart document.
