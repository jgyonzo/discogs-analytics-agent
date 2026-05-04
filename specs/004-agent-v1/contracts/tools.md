# Contract: Tools

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md)

The agent implements **seven tools** (≥ 5 per FR-022 / SC-006).
Tools are local Python objects, not MCP endpoints. Each tool is
a callable bound to a `tool_name`, with a typed input model and
a typed output model. Every invocation is recorded in
`agent_tool_calls` via the persistence shim defined in
[`graph.md` §3](./graph.md).

---

## 1. Tool registry

| # | Name | Purpose |
|---|------|---------|
| 1 | `dataset_schema_reader` | Open the published DuckDB read-only and return its allowlisted shape. |
| 2 | `query_classifier` | Classify a user query into the four complexity buckets and pick a model tier. |
| 3 | `sql_safety_checker` | Two-pass safety validation (AST + EXPLAIN) on extracted SQL. |
| 4 | `sandbox_executor` | Run generated Python in the restricted subprocess. |
| 5 | `chart_validator` | Verify execution produced a valid chart artifact. |
| 6 | `cost_logger` | Record an LLM call's tokens and estimated cost. |
| 7 | `artifact_store` | Resolve / persist artifact metadata. |

---

## 2. I/O schemas

All inputs and outputs are Pydantic v2 models.

### 2.1 `dataset_schema_reader`

```python
class SchemaReaderInput(BaseModel):
    duckdb_path: str

class TableColumn(BaseModel):
    name: str
    type: str

class SchemaReaderOutput(BaseModel):
    tables: dict[str, list[TableColumn]]    # only allowlisted tables
    has_master_fact: bool
    warnings: list[str] = []                # e.g. "Found stg_releases — filtered out per allowlist"
    captured_at: str                        # ISO timestamp
```

**Behavior**:
- Connects via `duckdb.connect(path, read_only=True)`.
- Lists tables/views via `information_schema.tables`.
- Filters to the allowlist
  (`release_fact`, `release_unique_view`,
  `release_artist_bridge`, `release_label_bridge`,
  optional `master_fact`).
- For each, lists columns via `information_schema.columns`.
- Records any non-allowlisted tables found in the file as
  warnings (defense-in-depth observability).

---

### 2.2 `query_classifier`

```python
class ClassifierInput(BaseModel):
    user_query: str
    schema_context: SchemaReaderOutput

class ClassifierOutput(BaseModel):
    complexity: Literal["simple", "complex", "unsupported", "clarification_needed"]
    selected_model: str | None              # null for unsupported / clarification_needed
    rationale: str
```

**Behavior**:
- Wraps the cheap-tier LLM with the `router.md` prompt.
- The LLM returns JSON; the tool validates against
  `ClassifierOutput`.
- Schema-aware: if the query references a column/concept not
  in the allowlist, the classifier MUST return `unsupported`.

---

### 2.3 `sql_safety_checker`

```python
class SafetyInput(BaseModel):
    generated_code: str

class SafetyViolation(BaseModel):
    rule: str           # e.g., "forbidden_table", "forbidden_keyword", "ddl_dml"
    detail: str         # specific token / table name

class SafetyOutput(BaseModel):
    allowed: bool
    extracted_sql: str | None       # null if extraction failed
    violations: list[SafetyViolation] = []
    explain_plan: str | None        # the DuckDB EXPLAIN output for trace
```

**Behavior**: see [`sql-safety.md`](./sql-safety.md).

---

### 2.4 `sandbox_executor`

```python
class SandboxInput(BaseModel):
    generated_code: str
    thread_id: str
    run_id: str
    timeout_seconds: int = 30

class SandboxOutput(BaseModel):
    exit_code: int
    stdout: str                     # capped at 16 KiB
    stderr: str                     # capped at 16 KiB
    duration_ms: int
    result: dict | None             # the RESULT object from the script, if produced
    exception_type: str | None      # e.g., "TimeoutError", "DuckDBError"
    exception_message: str | None
```

**Behavior**: see [`code-generation.md` §3](./code-generation.md).

The sandbox **does not** retry; retries live at the graph
level. The sandbox just runs once and reports.

---

### 2.5 `chart_validator`

```python
class ValidatorInput(BaseModel):
    execution_result: SandboxOutput
    expected_chart_dir: str         # /app/artifacts/<thread_id>/<run_id>

class ValidationError(BaseModel):
    rule: str
    detail: str

class ValidatorOutput(BaseModel):
    valid: bool
    errors: list[ValidationError] = []
    chart_path: str | None
    chart_bytes: int | None
    chart_type: str | None          # e.g., "bar", "line" — extracted from RESULT
    row_count: int | None
```

**Behavior**: walks the validation checklist in
[`graph.md` §2.7](./graph.md).

---

### 2.6 `cost_logger`

```python
class CostInput(BaseModel):
    node_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int

class CostOutput(BaseModel):
    usage_id: str               # the id of the agent_model_usage row written
    estimated_cost_usd: float | None
    rate_card_version: str      # "openai-2026-04" or "unknown"
```

**Behavior**:
- Looks up `model_name` in `llm/pricing.py` rate card.
- If found: computes `estimated_cost_usd` as
  `prompt_tokens * P + completion_tokens * Q` where `P` and
  `Q` are per-token rates. Returns the cost.
- If not found: `estimated_cost_usd = null`,
  `rate_card_version = "unknown"`. A warning is logged.
- Writes a row to `agent_model_usage`.

**Caller contract** (Constitution Principle VII.a — Configuration
sources): the `model_name` argument MUST reflect the model the calling
node *actually* invoked. It MUST be sourced from `settings.CHEAP_MODEL`
/ `settings.STRONG_MODEL`, or from `state["route"].selected_model`.
Hardcoded model literals in the call site are forbidden — they cause
the cost-log row to lie when the operator overrides a model in `.env`.
Nodes that always run on a fixed tier (e.g. `router`,
`response_synthesizer`) pass `settings.CHEAP_MODEL`; nodes whose tier
depends on routing (e.g. `query_understanding`, `code_generator`) pass
`state["route"].selected_model`.

---

### 2.7 `artifact_store`

```python
class ArtifactInput(BaseModel):
    run_id: str
    thread_id: str
    artifact_type: str              # V1 only "plotly_html"
    path: str
    metadata: dict = {}

class ArtifactOutput(BaseModel):
    artifact_id: str
    url: str                        # /artifacts/<artifact_id>
```

**Behavior**:
- Asserts `path` is inside `ARTIFACTS_DIR/<thread_id>/<run_id>/`
  (path-traversal guard).
- Asserts file exists and (when `artifact_type =
  plotly_html`) ends with `.html`.
- Writes to `agent_artifacts`.
- Returns the new `artifact_id` and the `/artifacts/{id}`
  URL.

---

## 3. Node-tool allowlist

Each graph node may invoke only tools listed for it. The
agent's runtime enforces this — calling a non-allowlisted tool
from a node raises `ToolNotAllowedError`. This is the
"allowlisted per node" requirement from FR-022.

| Node | Allowed tools |
|------|---------------|
| `load_schema` | `dataset_schema_reader` |
| `router` | `query_classifier`, `cost_logger` |
| `query_understanding` | `dataset_schema_reader`, `cost_logger` |
| `code_generator` | `cost_logger` |
| `sql_safety_checker` | `sql_safety_checker` |
| `sandbox_executor` | `sandbox_executor`, `artifact_store` |
| `chart_validator` | `chart_validator` |
| `response_synthesizer` | `artifact_store`, `cost_logger` |

Notes:
- `cost_logger` appears wherever an LLM call happens
  (`router`, `query_understanding`, `code_generator`,
  `response_synthesizer`).
- `dataset_schema_reader` is allowed in `query_understanding`
  for cache lookup; it doesn't re-open DuckDB.
- The persistence shim is **not** a tool — it's
  infrastructure that runs after every node regardless.

---

## 4. Tool persistence contract

Every `Tool.__call__()` is wrapped by the `@traced_tool`
decorator (in `tools/base.py`) which:

1. Records start time.
2. Catches exceptions; on failure, sets `status = "failed"`
   and `error_message = str(exc)`; re-raises.
3. On success, sets `status = "succeeded"` and
   `output_json = output.model_dump()`.
4. Records end time, computes `latency_ms`.
5. Inserts a row into `agent_tool_calls`.

The wrapper takes `node_name` from a contextvar set at the
top of each node function — so individual tools don't need
to know which node invoked them.

**Sensitive-field redaction**: the wrapper redacts known
secret keys (e.g., any field named `api_key`,
`OPENAI_API_KEY`) from `input_json` before insert. V1 tools
don't accept such inputs, but the redaction layer is in
place defensively.

---

## 5. Five-distinct-tools assertion

SC-006 requires ≥ 5 distinct tool types invoked across the
golden runs. The mapping (verified by the
`test_distinct_tools_count` test):

| Tool | Invoked on | Per-run count (typical) |
|------|------------|-------------------------|
| `dataset_schema_reader` | every run (cache hit after first) | 1 |
| `query_classifier` | every run | 1 |
| `cost_logger` | every LLM call | 2–4 |
| `sql_safety_checker` | every code-generating run | 1–3 (with retries) |
| `sandbox_executor` | every code-generating run | 1–3 |
| `chart_validator` | every code-generating run | 1–3 |
| `artifact_store` | every successful run | 1 |

A single successful simple run exercises all 7 tools at least
once. The assertion test counts distinct `tool_name`s across a
golden run and asserts ≥ 5 (7 expected; ≥ 5 gives slack for
controlled-failure paths).
