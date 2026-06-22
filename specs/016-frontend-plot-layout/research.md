# Phase 0 Research: Frontend Plot Layout & ID Copy

No `NEEDS CLARIFICATION` markers were carried from the spec. This document
records the design decisions and the alternatives weighed for each of the
three user stories.

## R1 — Where does the legend-orientation change actually live? (US2)

**Decision**: Add a single `fig.update_layout(...)` call to the canonical
"Required code shape" in `agent/src/discogs_agent/prompts/code_generator.md`
that places the legend horizontally below the plot, e.g.:

```python
fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2,
                              xanchor="center", x=0.5))
```

**Rationale**: The chart reaches the frontend as fully-rendered, opaque
Plotly HTML and is displayed inside a `sandbox="allow-scripts"` iframe
with no `allow-same-origin`. The frontend cannot (and per its security
posture must not) reach into that document to reposition a legend.
Legend placement is therefore a property of how the chart is generated.
Baking the `update_layout` call into the *canonical code shape* (rather
than only describing it in prose) maximizes LLM adherence, mirroring how
012–014 steered generated code through the same template.

**Alternatives considered**:
- *Frontend CSS / iframe manipulation* — rejected: opaque cross-origin
  iframe content is unreachable, and reaching in would breach the sandbox
  posture (Principle VI security note).
- *Deterministic server-side post-processing of the chart HTML* —
  rejected: the agent has no central chart-rendering chokepoint (the
  sandbox executes the LLM's own `fig.write_html`), so there is no clean
  injection point without re-architecting the sandbox result path. Out of
  proportion to a styling tweak.
- *Prose-only instruction (no template line)* — rejected as the sole
  mechanism: lower adherence than embedding it in the copied code shape.
  We do both (template line + a short note) for belt-and-suspenders.

**Known limitation**: Generated code is LLM-authored, so adherence is
high-but-not-guaranteed. SC-003 ("100% of new legend-bearing charts")
is the target; in practice it is measured on the curated question set and
treated as a strong default, not a hard runtime invariant. This is an
acceptable posture for a presentational default and is noted in the
contract.

## R2 — Grid rebalance ratio (US1)

**Decision**: Change `App.tsx`'s wide-layout grid template from
`lg:grid-cols-[20rem_1fr_1fr]` to give the result column the largest
share while keeping the conversation usable. Target:
`lg:grid-cols-[18rem_minmax(22rem,0.9fr)_1.6fr]` (suggested-questions
rail slightly narrower, conversation gets a sane minimum width, result
column ~1.6× the conversation's flexible share).

**Rationale**: The spec asks for "more space for plots, reduce a bit the
conversation". A `minmax()` floor on the conversation column prevents the
wider result column from squeezing the chat below a readable width
(Edge Case: conversation must stay usable; FR-002, SC-006). The result
column being the dominant flexible track satisfies FR-001/FR-004/SC-001.
The single-column stacked layout for narrow viewports
(`grid-cols-1`) is untouched, satisfying FR-003.

**Alternatives considered**:
- *Equal `1fr 1.5fr`* without a conversation floor — rejected: at smaller
  desktop widths the conversation could collapse too far.
- *Collapsible/hideable conversation* — rejected: larger scope than "a
  bit" of rebalancing; not requested.
- *Resizable splitter* — rejected: adds interaction + state for a Demo-Day
  polish item; over-engineered for "reduce a bit".

The exact rem/fr numbers are an implementation detail; the contract pins
the *ordering invariant* (result wider than conversation) and the
*usability floor*, not the precise pixels.

## R3 — Copy-to-clipboard mechanism (US3)

**Decision**: Add a small icon button (lucide-react `Copy` → `Check` on
success) next to the run-id and thread-id badges in `RunMetadata.tsx`.
On click it calls `navigator.clipboard.writeText(fullId)` with the
**full** id (not the truncated display value), shows a transient "copied"
state (~1.5s, `Check` icon), and is wrapped in try/catch so a rejected or
unavailable clipboard leaves no success state and throws nothing to the
UI.

**Rationale**:
- `navigator.clipboard.writeText` is the standard async clipboard API,
  available in the secure browser contexts the SPA runs in. It returns a
  promise that rejects on permission denial / insecure context — caught
  to satisfy FR-010 (no false success, no crash).
- lucide-react and clsx are already dependencies — no new packages
  (keeps the change dependency-neutral).
- The copy control sits in the run-metadata area shown with the chart,
  matching the spec's "in the chart visualization" intent (Assumption:
  copy location) without touching the opaque iframe.

**Accessibility (FR-011)**: the control is a real `<button>` with an
`aria-label` (e.g. "Copy run id"); the copied state is conveyed with an
`aria-live`/title update so assistive tech announces success. It is
keyboard-focusable and Enter/Space-activatable by virtue of being a
button.

**Conditional render (FR-012)**: the copy button is part of the existing
per-id badge, which already renders only when the id is present, so a
missing run_id/thread_id yields no orphan control.

**Alternatives considered**:
- *`document.execCommand("copy")`* — rejected: deprecated; the async
  Clipboard API is the current standard and gives a clean promise to
  catch.
- *Copy on clicking the badge itself* — rejected: less discoverable and
  conflicts with the existing hover-tooltip affordance; an explicit icon
  button is clearer and easier to label for a11y.
- *A toast/snackbar for confirmation* — rejected: heavier than needed; an
  inline icon swap is sufficient and local to the control.

## R4 — Testing approach

**Decision**: Extend `frontend/tests/components/RunMetadata.test.tsx`
with cases for: (a) clicking copy writes the **full** id (mock
`navigator.clipboard.writeText`, assert called with the untruncated
value), (b) a "copied" confirmation appears after success, (c) the copy
control has an accessible name, (d) a rejected clipboard promise does not
surface a success state and does not throw. The layout change (US1) is a
className/grid-template edit verified by `npm run typecheck` + visual
check via the quickstart; it is not unit-asserted beyond confirming the
component tree still renders (existing `full-flow` integration test
covers render). The agent prompt change (US2) is verified by inspecting
the rendered prompt / generated chart per the quickstart.

**Rationale**: Matches the existing frontend test conventions (Vitest +
Testing Library, `data-testid` selectors already present on the badges).
Mocking the clipboard is the standard way to assert copy behavior in
jsdom (no real clipboard).
