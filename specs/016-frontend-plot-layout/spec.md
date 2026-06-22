# Feature Specification: Frontend Plot Layout & ID Copy

**Feature Branch**: `016-frontend-plot-layout`  
**Created**: 2026-06-22  
**Status**: Draft  
**Input**: User description: "I want some improvements to the frontend: 1) more space for the plots, reduce a bit the space for the conversation and always place the plot legends down not on the side. 2) add a copy button to the run id and thread id in the chart visualization"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - More room for the chart, less for the conversation (Priority: P1)

A person demoing or exploring the agent asks a question and wants the
resulting chart to be the visual focus of the screen. Today the screen
is split into three side-by-side regions (suggested questions, the
conversation, and the result) where the conversation and the result get
roughly equal width, so wide charts feel cramped. This story rebalances
the layout so the result region (which holds the chart) is visibly
wider than the conversation region, while the conversation remains fully
usable for typing and reading turns.

**Why this priority**: The chart is the product's payoff — the thing the
audience looks at. Making it the largest, clearest region delivers the
most value for the least change and is the headline ask.

**Independent Test**: Load the app at a typical desktop width, run a
question, and confirm the chart region is wider than the conversation
region and that wide charts render with less horizontal cropping than
before — without breaking the ability to read/scroll the conversation
or type a new question.

**Acceptance Scenarios**:

1. **Given** the app is open on a wide desktop viewport, **When** the
   page loads, **Then** the result region (containing the chart) is
   allocated more horizontal space than the conversation region.
2. **Given** a question has produced a chart, **When** the chart renders,
   **Then** it occupies more horizontal space than it did under the
   previous equal split, so labels and series are easier to read.
3. **Given** the conversation region is narrower than before, **When** a
   user reads prior turns and types a new question, **Then** the
   conversation history and the input box remain fully readable and
   usable (no clipped controls, no loss of scroll).
4. **Given** a narrow / mobile-width viewport, **When** the page loads,
   **Then** the regions stack vertically as they do today (the rebalance
   applies to the wide multi-column layout only).

---

### User Story 2 - Chart legends always sit below the plot (Priority: P2)

When a chart includes a legend (e.g. multiple series, categories, or pie
slices), the audience should see the maximum possible plotting area.
Legends placed to the side steal horizontal width — exactly the width
this feature is trying to give back to the chart. This story makes every
generated chart place its legend horizontally beneath the plot rather
than to the right/side.

**Why this priority**: Reinforces US1's goal (wider effective plot area)
and gives charts a consistent, predictable look across questions. It is
P2 because US1 already delivers a visible improvement on its own, and
legend placement is a refinement on top of it.

**Independent Test**: Run a question whose chart has a legend (multiple
series or a categorical breakdown) and confirm the legend appears below
the plot, oriented horizontally, for that chart and for other
legend-bearing chart types.

**Acceptance Scenarios**:

1. **Given** a question produces a chart with multiple series or
   categories, **When** the chart renders, **Then** its legend appears
   below the plotting area, not to the side.
2. **Given** charts of different kinds that show legends (e.g. line, bar,
   pie), **When** each renders, **Then** the legend is consistently
   placed below the plot.
3. **Given** a chart that has no legend, **When** it renders, **Then**
   the change has no adverse effect (no empty legend strip, no broken
   layout).

---

### User Story 3 - Copy the run id and thread id with one click (Priority: P3)

An operator or developer looking at a result wants to grab the full run
id or thread id to look it up in logs, persistence, or a support thread.
Today these ids are shown truncated as small badges and the full value
is only available via hover tooltip — there is no reliable way to copy
the complete value. This story adds a one-click copy affordance to the
run id and thread id shown with the chart/result, copying the full
(untruncated) value to the clipboard with clear visual confirmation.

**Why this priority**: Valuable for debugging and support but used by a
narrower audience than the chart-viewing improvements, so it ranks below
the layout changes. It is fully independent and can ship on its own.

**Independent Test**: Run a question, click the copy affordance next to
the run id, and confirm the full run id (not the truncated display
value) is on the clipboard and that the UI confirms the copy; repeat for
the thread id.

**Acceptance Scenarios**:

1. **Given** a result with run metadata is displayed, **When** the user
   activates the copy control next to the run id, **Then** the full,
   untruncated run id is placed on the clipboard.
2. **Given** a result with run metadata is displayed, **When** the user
   activates the copy control next to the thread id, **Then** the full,
   untruncated thread id is placed on the clipboard.
3. **Given** the user has just copied an id, **When** the copy succeeds,
   **Then** the UI shows a brief, clear confirmation (e.g. a "copied"
   state) so the user knows it worked.
4. **Given** a keyboard-only user, **When** they navigate to the copy
   control, **Then** it is reachable and operable via keyboard and
   labeled for assistive technology.

---

### Edge Cases

- **No chart / no result yet**: When no question has been run, the result
  region shows its existing empty state; the rebalanced widths still
  apply and the layout does not collapse.
- **Very wide vs. narrow charts**: The wider result region must not force
  the conversation region below a usable minimum width; the conversation
  must retain enough width to read turns and type.
- **Legend with many entries**: A horizontally-placed legend with many
  entries should wrap/scroll within the chart area rather than overflow
  the chart container or push the chart off-screen.
- **Clipboard unavailable / denied**: If the clipboard cannot be written
  (browser permission denied or unsupported context), the copy control
  must fail gracefully without crashing the UI and should not falsely
  show a success confirmation.
- **Missing run/thread id**: If a result lacks a run id or thread id, the
  corresponding copy control is not shown (consistent with today's
  render-only-present-fields behavior).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: On wide (multi-column) viewports, the system MUST allocate
  the result region (which contains the chart) more horizontal space
  than the conversation region.
- **FR-002**: The system MUST reduce the conversation region's horizontal
  space relative to today's equal split, while keeping the conversation
  history readable/scrollable and the question input fully usable.
- **FR-003**: On narrow viewports, the system MUST preserve the current
  stacked (single-column) behavior; the rebalance applies only to the
  wide layout.
- **FR-004**: The chart MUST make use of the additional horizontal space
  so wide charts render with less cropping than under the previous split.
- **FR-005**: Generated charts that include a legend MUST place the
  legend below the plotting area, oriented horizontally, rather than to
  the side.
- **FR-006**: The legend placement change MUST apply consistently across
  the chart kinds the agent can produce, and MUST NOT degrade charts that
  have no legend.
- **FR-007**: The system MUST provide a copy control for the run id shown
  with a result that, when activated, places the full untruncated run id
  on the clipboard.
- **FR-008**: The system MUST provide a copy control for the thread id
  shown with a result that, when activated, places the full untruncated
  thread id on the clipboard.
- **FR-009**: After a successful copy, the system MUST show a brief,
  clear confirmation indicating the value was copied.
- **FR-010**: If copying to the clipboard fails, the system MUST NOT show
  a success confirmation and MUST NOT crash or break the surrounding UI.
- **FR-011**: Copy controls MUST be keyboard-operable and labeled for
  assistive technologies.
- **FR-012**: A copy control MUST appear only when its corresponding id
  is present (no control for a missing run id or thread id).

### Key Entities *(include if feature involves data)*

- **Run metadata**: The per-result information displayed alongside the
  chart, including the run id and thread id (and existing status,
  complexity, model badges). The run id and thread id are the values this
  feature lets users copy in full.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a wide desktop viewport, the result region is wider than
  the conversation region (result region receives a clearly larger share
  of the row's width than the conversation region).
- **SC-002**: For a representative wide chart, the visible plotting width
  increases compared to the previous equal-split layout.
- **SC-003**: 100% of newly generated charts that contain a legend
  display that legend below the plot rather than to the side.
- **SC-004**: A user can copy the full run id or thread id in a single
  click/activation, and the copied clipboard value exactly matches the
  full id (not the truncated display value).
- **SC-005**: After copying, users receive visible confirmation within a
  moment of the action, so success is unambiguous.
- **SC-006**: The conversation region remains usable after the rebalance:
  users can still read prior turns and submit a new question without
  clipped or inaccessible controls.

## Assumptions

- **Cross-component scope**: The layout-space change (US1) and the
  copy-button change (US3) are frontend-only. The legend-placement change
  (US2) affects how charts are generated upstream, because the chart is
  delivered to the frontend as opaque rendered HTML the frontend treats
  as a black box; the frontend cannot reposition a legend inside an
  already-rendered chart. US2 is therefore expected to be satisfied by
  changing chart-generation guidance, not the frontend. The exact
  component split is an implementation detail for planning.
- **Space split**: "More space for plots, reduce a bit for the
  conversation" is interpreted as a moderate rebalance (the result region
  becomes the widest of the three regions and the conversation becomes
  noticeably narrower than the result), not an extreme one that makes the
  conversation unusable. The suggested-questions region keeps roughly its
  current narrow width. The precise ratio is chosen during implementation
  to keep the conversation usable.
- **Legend orientation**: "Legends down not on the side" is interpreted
  as a horizontal legend positioned beneath the plot, applied uniformly
  to all legend-bearing charts.
- **Copy location**: "In the chart visualization" is interpreted as the
  run-metadata area shown together with the chart/result (where the run
  id and thread id already appear as badges), not inside the opaque chart
  iframe itself.
- **Full value copied**: The copy action copies the complete id even
  though the on-screen badge shows a truncated form.
- **No backend/API changes**: No changes to the agent's HTTP API
  surface, persistence schema, or the result payload are required; run id
  and thread id are already delivered to the frontend.
- **Existing security posture preserved**: The chart continues to render
  as opaque HTML in the sandboxed iframe; this feature does not relax the
  iframe sandbox or have the frontend read into the chart's contents.
