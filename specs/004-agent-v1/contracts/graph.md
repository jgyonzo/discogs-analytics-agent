# Contract: LangGraph

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md)

The LangGraph layer is implemented as a single compiled
`StateGraph[AgentState]` with eight nodes, fixed topology, and
explicit conditional edges. The state contract is in
[../data-model.md §2.1](../data-model.md). This file is the
contract for the **graph itself**: nodes, transitions, retry
semantics, and the persistence shim that mirrors trace events
to Postgres after every node.

---

## 1. Topology

```text
                 ┌───────────────────────────────────────────┐
                 │                                           │
START → load_schema → router ─┬→ unsupported ──→ response_synthesizer → END
                              ├→ clarification_needed ─→ ─┘
                              └→ supported (simple|complex)
                                  ↓
                          query_understanding
                                  ↓
                          code_generator ←──────────────────┐
                                  ↓                          │
                          sql_safety_checker                  │ retry edge
                              ├→ unsafe & retries left ──────┤
                              ├→ unsafe final ──→ response_synthesizer → END
                              └→ safe                          │
                                  ↓                            │
                          sandbox_executor                     │
                                  ↓                            │
                          chart_validator                      │
                              ├→ invalid & retries left ──────┘
                              ├→ invalid final ─→ response_synthesizer → END
                              └→ valid → response_synthesizer → END
```

The graph has 8 nodes (≥ 4 per FR-006) and 2 retry edges (the
safety retry and the validation retry both loop back to
`code_generator`). The retry counter is shared across both
edges — a run that consumes 1 safety retry then fails
validation can use 1 more validation retry before exhaustion,
up to `max_retries` (default 2) total.

---

## 2. Node specifications

Each node is a pure function `AgentState → AgentState` (no
side effects on the graph state owned by other nodes). Side
effects: tool invocations, LLM calls, sandbox execution, file
writes — all of which are recorded into the `tool_calls` /
`model_usage` / `errors` accumulators in state and projected
to Postgres by the persistence shim.

### 2.1 `load_schema`

**Purpose**: build the `SchemaContext` once per process. Caches
in module state; reads from cache on subsequent invocations.

**Reads**: env (`ANALYTICS_DUCKDB_PATH`).
**Writes**: `state.schema_context`.
**Tools allowed**: `dataset_schema_reader`.
**LLM**: none.

**Failure modes**:
- DuckDB file missing / unreadable → raise; the API converts
  to `503 duckdb_unavailable` and records an
  `error_type=unexpected` row.

---

### 2.2 `router`

**Purpose**: classify the user query into
`{simple, complex, unsupported, clarification_needed}` and
pick the model tier.

**Reads**: `state.user_query`, `state.schema_context`.
**Writes**: `state.route` =
`{complexity, selected_model, rationale}`.
**Tools allowed**: `query_classifier`, `cost_logger`.
**LLM**: cheap-tier (`gpt-4o-mini`). The router itself uses
the cheap tier even for complex queries; the *selected model
for downstream code generation* is what `selected_model`
records.

**Output rules**:
- `complexity = unsupported` ⇒ `selected_model = null`.
- `complexity = clarification_needed` ⇒ `selected_model = null`.
- `complexity = simple` ⇒ `selected_model = $CHEAP_MODEL`.
- `complexity = complex` ⇒ `selected_model = $STRONG_MODEL`.

**Conditional edge** (`router → next`):

```python
def router_edge(state: AgentState) -> Literal["query_understanding", "response_synthesizer"]:
    c = state["route"]["complexity"]
    if c in ("unsupported", "clarification_needed"):
        return "response_synthesizer"
    return "query_understanding"
```

---

### 2.3 `query_understanding`

**Purpose**: build the analytical plan. The plan is what
`code_generator` translates into Python+SQL.

**Reads**: `state.user_query`, `state.schema_context`,
`state.thread_id` (to fetch carry-over from Postgres).
**Writes**: `state.query_plan`,
`state.carryover_preamble`, `state.carryover_turn_count`.
**Tools allowed**: `dataset_schema_reader` (cache lookup,
counts as a tool call for trace purposes).
**LLM**: tier from `state.route.selected_model`.

**Carry-over logic** (R-04):

```python
last_turns = repo.fetch_recent_runs(
    thread_id=state["thread_id"],
    limit=config.THREAD_CARRYOVER_TURNS,
    statuses=("succeeded", "failed_clarification_needed"),
)
preamble, n = build_carryover_preamble(
    last_turns,
    token_budget=config.THREAD_CARRYOVER_TOKEN_BUDGET,
)
state["carryover_preamble"] = preamble  # may be None
state["carryover_turn_count"] = n
```

The preamble (when non-empty) is injected into the
`query_understanding` prompt template. Generated SQL/code
from prior runs is **not** included.

**Output `query_plan` shape** (mirrors canonical doc Section 9.3):

```json
{
  "analysis_intent": "trend",
  "tables": ["release_fact"],
  "dimensions": ["year"],
  "metrics": [
    {"name": "releases", "aggregation": "count_distinct", "column": "release_id"}
  ],
  "filters": [{"column": "style", "operator": "=", "value": "Techno"}],
  "chart_type": "line",
  "notes": "Use COUNT(DISTINCT release_id) because release_fact is release x style."
}
```

---

### 2.4 `code_generator`

**Purpose**: produce executable Python with embedded SQL,
following the code-generation contract (see
[`./code-generation.md`](./code-generation.md)).

**Reads**: `state.user_query`, `state.query_plan`,
`state.schema_context`, `state.safety_result`,
`state.validation_result`, `state.execution_result`,
`state.retry_count`.
**Writes**: `state.generated_code`, increments
`state.retry_count`.
**Tools allowed**: `cost_logger`.
**LLM**: tier from `state.route.selected_model`.

**Prompt selection**:
- On first entry (`retry_count == 0`): the
  `code_generator.md` prompt.
- On re-entry (`retry_count > 0`): the `repair_code.md`
  prompt, which receives the prior generated code, the
  failure details (`safety_result.violations` or
  `validation_result.errors`), and the original plan.

**Side effect**: increments `state.retry_count` so retry edges
can guard on it.

---

### 2.5 `sql_safety_checker`

**Purpose**: gate execution. Extracts SQL from the generated
code and validates against the allowlist (see
[`./sql-safety.md`](./sql-safety.md)).

**Reads**: `state.generated_code`.
**Writes**: `state.generated_sql` (the extracted SQL),
`state.safety_result` = `{allowed: bool, violations: [...]}`.
**Tools allowed**: `sql_safety_checker`.
**LLM**: none.

**Conditional edge** (`sql_safety_checker → next`):

```python
def safety_edge(state) -> Literal["sandbox_executor", "code_generator", "response_synthesizer"]:
    if state["safety_result"]["allowed"]:
        return "sandbox_executor"
    if state["retry_count"] < state["max_retries"]:
        return "code_generator"             # retry with repair prompt
    return "response_synthesizer"           # exhausted → controlled failure
```

When routing to `response_synthesizer` due to exhaustion, the
final `agent_runs.status` becomes `failed_safety`.

---

### 2.6 `sandbox_executor`

**Purpose**: run the validated code in the restricted
subprocess (see [`./code-generation.md` §3](./code-generation.md)
for the sandbox contract).

**Reads**: `state.generated_code`, `state.thread_id`,
`state.run_id`.
**Writes**: `state.execution_result` =
`{exit_code, stdout, stderr, result, duration_ms,
exception_type, exception_message}`,
`state.artifact_paths`, `state.dataframe_preview`.
**Tools allowed**: `sandbox_executor`, `artifact_store`.
**LLM**: none.

**Failure modes**:
- Subprocess crashes → `execution_result.exit_code != 0`,
  `exception_*` populated.
- Wall-clock timeout → subprocess killed; `exit_code = -9`
  (or platform equivalent), `exception_type = "timeout"`.
- Either failure: still flows to `chart_validator` (the
  validator will mark it invalid; the retry decision lives
  there).

---

### 2.7 `chart_validator`

**Purpose**: confirm the run produced what it should
(see FR-019).

**Reads**: `state.execution_result`, `state.artifact_paths`,
`state.dataframe_preview`.
**Writes**: `state.validation_result` =
`{valid: bool, errors: [...], should_retry: bool}`.
**Tools allowed**: `chart_validator`.
**LLM**: none.

**Validation checklist** (any false → `valid = false`):
1. `execution_result.exit_code == 0`.
2. `execution_result.exception_type is None`.
3. `RESULT` was returned and is a `dict`.
4. `RESULT.chart_path` exists on disk and is inside
   `ARTIFACTS_DIR/{thread_id}/{run_id}/`.
5. `RESULT.chart_path` ends with `.html`.
6. `RESULT.dataframe_preview` is a list (may be empty for
   genuinely-empty queries — see "documented empty-result
   case" in FR-019).
7. `RESULT.row_count` is an int and matches the underlying
   dataframe size.

**`should_retry` logic**:

```python
should_retry = (not valid) and state["retry_count"] < state["max_retries"]
```

**Conditional edge**:

```python
def validation_edge(state) -> Literal["response_synthesizer", "code_generator"]:
    if state["validation_result"]["valid"]:
        return "response_synthesizer"
    if state["validation_result"]["should_retry"]:
        return "code_generator"
    return "response_synthesizer"           # exhausted → controlled failure
```

When routing to `response_synthesizer` due to exhaustion,
final `agent_runs.status` becomes `failed_validation`.

---

### 2.8 `response_synthesizer`

**Purpose**: produce the final user-facing reply, regardless
of which terminal we reached.

**Reads**: everything (this node's job is to render the run).
**Writes**: `state.final_response`.
**Tools allowed**: `artifact_store`, `cost_logger`.
**LLM**: cheap tier — even for complex runs the synthesis is
short and stylistic.

**Branch table** (chosen by `state.route.complexity` +
validation/safety state):

| Path | Behavior |
|------|----------|
| Successful (`validation_result.valid == true`) | Short summary referencing the chart artifact and the SQL. |
| `unsupported` | Explanation of *why* (referencing the missing field) + listing of available tables/views and example questions they can answer. |
| `clarification_needed` | Asks a focused follow-up question identifying the missing dimension/metric. |
| `failed_safety` | "I couldn't safely answer that — the generated query referenced something not allowed by the data contract. Try rephrasing." (No mention of the specific forbidden table/keyword to avoid leaking implementation detail to a poking user.) |
| `failed_validation` | "I generated code but couldn't produce a valid chart after retrying. Try rephrasing." |
| `failed_internal` (rare) | "Something unexpected went wrong. The error is logged with run_id `<id>`." |

**The synthesizer's prompt MUST forbid raw tracebacks** in the
output (FR-024).

---

## 3. Persistence shim

After every node, a side-channel writes the node's deltas to
Postgres. This is implemented as a **post-node hook** wired
into the `StateGraph`'s `before_each` / `after_each` or as a
manual call at the end of every node function. Either is
acceptable; the constraint is that no node returns control to
the graph runner until its tool calls and model usage are
flushed to Postgres.

Sequence per node:

1. Node body runs, appending to
   `state.tool_calls` / `state.model_usage` / `state.errors`.
2. Persistence shim diffs against the last seen length and
   inserts the new rows.
3. Persistence shim updates the running `agent_runs` row's
   non-terminal fields if applicable (e.g., `complexity`,
   `selected_model`, `generated_sql`, `metadata.retry_count`).
4. Returns the (possibly mutated) state to the graph runner.

At graph **end**, the API layer:

1. Reads `state.final_response`, `state.status` (derived from
   the terminal path), and updates `agent_runs` to its final
   shape (`status`, `finished_at`, `latency_ms`,
   `final_response`).
2. Inserts the artifact row(s) (an artifact may be inserted
   inside the sandbox node already; the API only needs to
   confirm).

---

## 4. Compile-time invariants

- `max_retries` defaults to `config.MAX_RETRIES` (= 2). Test
  via env override.
- `retry_count` starts at 0. Incremented in `code_generator`
  on entry. After 2 increments, the next safety/validation
  failure routes to `response_synthesizer` (not
  `code_generator`).
- The graph's compiled JSON (or its `get_graph().draw_*`
  Mermaid output) is committed under
  `agent/docs/graph.mmd` for human inspection. (Optional but
  recommended.)
- Each node is unit-testable by calling it with a
  hand-constructed `AgentState` — no LangGraph runtime
  required.

---

## 5. Path test coverage (SC-004)

The `tests/graph/` suite asserts each path is reachable:

| Path test | Triggers |
|-----------|----------|
| `test_path_simple` | Stub: simple route, valid SQL, valid execution → END succeeded. |
| `test_path_complex` | Stub: complex route. |
| `test_path_unsupported` | Stub: router returns `unsupported`. |
| `test_path_clarification` | Stub: router returns `clarification_needed`. |
| `test_path_safety_retry` | Stub: 1st safety check fails, 2nd succeeds → END succeeded with `retry_count = 1`. |
| `test_path_validation_retry` | Stub: 1st execution invalid, 2nd valid → END succeeded with `retry_count = 1`. |
| `test_path_retries_exhausted` | Stub: 3 consecutive failures → END `failed_safety` or `failed_validation`. |

These tests use the LLM stub (R-08) and an in-memory SQLite
for persistence — full LangGraph runtime, no LLM, no Postgres
required.
