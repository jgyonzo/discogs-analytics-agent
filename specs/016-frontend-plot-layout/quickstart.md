# Quickstart: Verifying Frontend Plot Layout & ID Copy

This feature is three small, independently verifiable changes. Each maps
to one user story and can be checked on its own.

## Prerequisites

- The local docker-compose stack (or `npm run dev` in `frontend/` against
  a running agent) up, as in the 008 quickstart.
- For US2, the agent able to generate at least one chart (any curated
  question that yields a multi-series / categorical chart).

## US1 — More room for the chart, less for the conversation

1. Open the app on a wide desktop viewport (≥ `lg` breakpoint).
2. Run any curated question that produces a chart.
3. **Verify**:
   - The result column (right) is visibly **wider** than the conversation
     column (middle). (SC-001)
   - The chart uses the extra width — wide charts crop less than before.
     (SC-002)
   - You can still read the conversation history and type/submit a new
     question; no controls are clipped. (SC-006)
4. Narrow the window below the `lg` breakpoint and **verify** the regions
   stack vertically as before. (FR-003)

## US2 — Legends below the plot

1. Run a question whose chart has a legend (multiple series or a
   categorical breakdown), e.g. one that groups by a `style`/category.
2. **Verify** the legend renders **horizontally beneath** the plot, not on
   the right side. (SC-003)
3. Run a single-series chart and **verify** there is no empty legend strip
   or broken layout. (FR-006)
4. (Optional, deeper check) Inspect the generated code / rendered prompt
   and confirm the `fig.update_layout(legend=dict(orientation="h", ...))`
   call is present in the canonical code shape.

> Note: chart code is LLM-generated; legend-below is a strong default
> embedded in the code shape, not a hard runtime invariant. Spot-check
> across a few curated questions.

## US3 — Copy the run id and thread id

1. Run any question so the result panel shows the run-metadata badges.
2. Click the copy control on the **run** badge.
3. **Verify**:
   - A brief "copied" confirmation appears on that control. (SC-005)
   - Paste into any text field — the pasted value is the **full**,
     untruncated run id, not the `abc123…` display form. (SC-004)
4. Repeat for the **thread** badge.
5. Keyboard check: Tab to a copy control and activate with Enter/Space —
   it copies and is announced. (FR-011)
6. Failure check (optional): in a context where the clipboard is denied,
   activating the control shows **no** success confirmation and does not
   break the page. (FR-010)

## Automated tests

From `frontend/`:

```bash
npm run typecheck      # layout class change compiles
npm run test           # RunMetadata copy tests + existing suite
```

The extended `tests/components/RunMetadata.test.tsx` covers: full-id copy,
confirmation appearance, accessible name on the copy control, and graceful
handling of a rejected clipboard write.
