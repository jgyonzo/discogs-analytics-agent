# Contract: V1 curated question set

**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

This contract defines the seven curated questions that ship in `frontend/src/data/curatedQuestions.ts` for V1. The data file is normative — its contents must equal this list at merge time. Drift is detectable by `frontend/tests/integration/curated-questions-spread.test.ts`.

The set is sized at 7 (one above the spec's `≥ 5` floor; FR-005) so that at least one item can be removed during demo prep without breaking the spread coverage requirement.

---

## 1. The set

### Q1 — Releases by decade

- **title**: `Releases by decade`
- **category**: `Trends`
- **query**: `Show releases by decade as a bar chart`
- **description**: `Basic decade-grain release count using COUNT(DISTINCT release_id) FROM release_fact GROUP BY decade.`
- **demonstrates**: `["simple-aggregate", "time-series"]`

The "first thing to demo" question. Hits the smallest interesting analytical surface (`release_fact` + `decade` with `COUNT(DISTINCT release_id)`) and produces a chart everyone can interpret in one second. (Pre-013 this question's description claimed it used `release_unique_view`; the agent actually generates the `release_fact` form, which is strictly cheaper at catalog scale and remains the only safe shape under 013's tightened glossary.)

### Q2 — Techno over time

- **title**: `Techno over time`
- **category**: `Styles`
- **query**: `Show the evolution of Techno releases over time`
- **description**: `Line chart using release_fact and COUNT(DISTINCT release_id) over a style filter.`
- **demonstrates**: `["time-series", "simple-aggregate"]`

Tests that the agent can apply a style/genre filter (which exercises the `release_fact` joins and the `COUNT(DISTINCT release_id)` pattern Principle V calls out as load-bearing).

### Q3 — Vinyl vs. CD

- **title**: `Vinyl vs CD`
- **category**: `Formats`
- **query**: `Compare Vinyl and CD releases by decade`
- **description**: `Format comparison over time — exercises the has_*_format flags on release_fact.`
- **demonstrates**: `["format-comparison", "time-series"]`

Showcases the format-grain story (Principle V's `is_*` vs `has_*` distinction) without requiring the user to know about it.

### Q4 — Top countries

- **title**: `Top countries`
- **category**: `Geography`
- **query**: `What are the top 15 countries by number of releases?`
- **description**: `Ranking of countries by release count.`
- **demonstrates**: `["geographic-ranking", "simple-aggregate"]`

Common analytical pattern (`ORDER BY count DESC LIMIT 15`); the agent's output is a horizontal bar chart that's immediately readable.

### Q5 — Label diversity

- **title**: `Label diversity`
- **category**: `Labels`
- **query**: `Which labels have the most stylistic diversity?`
- **description**: `Complex query joining labels, releases, and styles; uses release_label_bridge.`
- **demonstrates**: `["label-diversity", "simple-aggregate"]`

The "showpiece complex" question. Hits the strong-model routing path and demonstrates the agent can author a multi-table join correctly. SC-010 is anchored on this question.

### Q6 — House outliers

- **title**: `House outliers`
- **category**: `Advanced`
- **query**: `Detect outlier years for House releases`
- **description**: `Outlier detection using z-scores or IQR over a style-filtered time series.`
- **demonstrates**: `["outlier-detection", "time-series"]`

Demonstrates non-trivial analytical methodology (z-score / IQR), which is Python-not-just-SQL territory and exercises the agent's code-generation path beyond aggregations.

### Q7 — Works with most versions

- **title**: `Works with most versions`
- **category**: `Masters`
- **query**: `Which works have the most versions?`
- **description**: `Uses master_fact (optional table) — exercises the master-grain join.`
- **demonstrates**: `["master-grain-join"]`

Conditional on `master_fact` being present in the published DuckDB (per `005/contracts/duckdb-schema.md` and the agent's `has_master_fact` health check). If `master_fact` is absent, the agent's classifier returns `failed_unsupported` with a friendly message — both outcomes are demonstrable.

---

## 2. Spread coverage requirement

The seven `demonstrates` tags collectively cover all seven `AgentCapability` values:

| Capability | Covered by |
|------------|-----------|
| `simple-aggregate` | Q1, Q2, Q4, Q5 |
| `time-series` | Q1, Q2, Q3, Q6 |
| `format-comparison` | Q3 |
| `geographic-ranking` | Q4 |
| `label-diversity` | Q5 |
| `outlier-detection` | Q6 |
| `master-grain-join` | Q7 |

Drop-one safety: removing any single question from the set still covers ≥ 5 distinct capabilities, so FR-005's "meaningful spread" requirement still holds.

---

## 3. Authoring rules for V1

- **Question text MUST be the actual user-facing prompt sent to the agent.** No placeholders, no parameter substitution. (V1 has no parameter UI.)
- **Question text MUST work against the published DuckDB at the time of demo.** This means: no references to `master_fact` columns that don't exist (only Q7 touches it, and is gated on its presence). No references to columns Principle V doesn't allow (`master_fact.title` is fine; `master_fact.price` is not — there is no price data).
- **`title` is ≤ 40 chars.** Long titles overflow the card; the spec calls for a clean demo-ready UI.
- **`description` is ≤ 100 chars.** Same constraint.
- **`category` is one of the seven enum values** (`Trends`, `Styles`, `Formats`, `Geography`, `Labels`, `Advanced`, `Masters`). Adding a new category is a contract change, not a styling tweak.

---

## 4. Future work (NOT V1)

- Backend-served curated questions (an endpoint returning the set) — would let us tune the demo without redeploying the frontend. V1 ships a static module.
- Per-question pre-rendered artifact previews (the "demo gallery" stretch in the brief §23) — would let the demo continue if the LLM is slow. V1 always asks live.
- "Learn more" links per question pointing at a write-up of what the underlying SQL does. Useful for evaluators reviewing the project; out of V1.

---

## 5. Verification

`frontend/tests/integration/curated-questions-spread.test.ts` (added during Phase 2 implementation) asserts:

- `curatedQuestions.length >= 5` (FR-005 floor).
- The union of all `demonstrates` arrays has size `>= 5` (the "meaningful spread" interpretation).
- Each entry has all required fields (`title`, `category`, `query`, `demonstrates`); `description` may be omitted per the type but is present for all V1 entries.
- `title.length <= 40` and `description.length <= 100` for all entries.
- `category` is one of the seven enum values.
