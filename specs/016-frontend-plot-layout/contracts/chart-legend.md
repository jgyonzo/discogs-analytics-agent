# Contract: Chart Legend Placement (agent code-generation)

Scope: `agent/` only — specifically the code-generation prompt asset
`agent/src/discogs_agent/prompts/code_generator.md`. No DuckDB-schema
change, so this is **not** a cross-component contract change under
Principle VI; it is an agent-internal generated-output convention.

## Requirement

- **G-1**: Generated charts that render a legend MUST place that legend
  **horizontally, below the plotting area**, rather than to the side.
  (FR-005)
- **G-2**: The placement convention MUST apply uniformly across the chart
  kinds the generator can emit (`bar | line | scatter | pie | histogram |
  box | area`). (FR-006)
- **G-3**: The convention MUST NOT degrade charts that have no legend (no
  empty legend strip, no broken layout). Plotly omits the legend region
  when there is nothing to show, so the `update_layout` call is inert for
  single-series charts. (FR-006, spec Edge Case)

## Mechanism

Amend the **"Required code shape"** block in `code_generator.md` so the
canonical template includes a legend-layout call immediately after the
figure is constructed, e.g.:

```python
fig = px.<chart_kind>(df, ...)
fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2,
                              xanchor="center", x=0.5))
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")
```

A one-line instruction accompanying the code shape SHOULD state the
intent ("place any legend horizontally below the plot") so the LLM keeps
the call when it adapts the template.

## Constraints & posture

- **Principle VII(b)**: This is a chart-**styling** directive. It MUST NOT
  describe tables, grains, columns, sample values, or catalog contents,
  and MUST NOT duplicate anything `{schema_context_block}` renders. The
  edit is confined to the code-shape/styling region of the prompt.
- **Adherence**: Generated code is LLM-authored; G-1 is a strong default
  enforced by embedding the call in the copied code shape, verified on the
  curated question set per `quickstart.md`. It is a presentational
  default, not a hard runtime invariant, and is not gated by an
  automated assertion in this feature.
- **No new forbidden/allowed tokens**: the existing SQL-safety and
  forbidden-import lists in the prompt are unchanged.
