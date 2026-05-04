# Data Model: Agent Schema Context Enrichment

The feature touches three logical data shapes:

1. The in-process `SchemaContext` payload (extended).
2. The `agent_runs.status` enum in Postgres (one new value).
3. The `chart_validator` tool's output shape (one new
   `reason` value).

Nothing about the published-DuckDB schema changes. Nothing
about the LangGraph `AgentState` shape changes — the enriched
schema-context fits inside the existing
`schema_context: dict[str, Any]` slot.

## 1. SchemaContext (in-process, agent-only)

Defined in `agent/src/discogs_agent/duckdb_layer/schema.py`.

### Existing shape (from 004-agent-v1)

```python
class SchemaContext(TypedDict):
    tables: dict[str, list[dict[str, str]]]
    has_master_fact: bool
    duckdb_path: str
    captured_at: str
    warnings: list[str]
```

### Extended shape (this feature)

```python
class SchemaContext(TypedDict):
    tables: dict[str, list[dict[str, str]]]
    has_master_fact: bool
    duckdb_path: str
    captured_at: str
    warnings: list[str]

    # --- New fields below ---
    sample_values: dict[str, dict[str, list[SampleValue]]]
    domain_glossary: list[str]
    published_run_id: str | None
    rendered_block: str    # cached pre-rendered string for prompts
    rendered_token_count: int
```

`sample_values` is keyed by `<table>` → `<column>` →
`list[SampleValue]`. Concretely:

```python
class SampleValue(TypedDict):
    value: str | int       # the distinct value (e.g., "Techno", 1990)
    count: int             # how many releases share that value
```

For example:

```python
sample_values = {
    "release_unique_view": {
        "primary_genre": [
            {"value": "Rock", "count": 5454580},
            {"value": "Electronic", "count": 4889274},
            ...
        ],
        "primary_format_group": [...],
        "decade": [{"value": 2010, "count": 6_xxx}, ...],
        "country": [...],   # top-20
    },
    "release_fact": {
        "style": [
            {"value": "House", "count": 800_xxx},
            {"value": "Techno", "count": 500_xxx},
            ...    # top-50
        ],
    },
}
```

`domain_glossary` is a small list of one-line domain rules
that the LLM reads before generating SQL/code:

```python
domain_glossary = [
    "primary_genre is the coarse bucket (Rock, Electronic, Pop, Jazz, ...). "
    "style is the granular subgenre (Techno, House, Ambient, ...). "
    "Filter by 'style' on release_fact for subgenre questions; "
    "filter by 'primary_genre' on release_unique_view only when the value "
    "literally appears in the primary_genre sample.",

    "For 'evolution / trend / over time' questions WITHOUT explicit yearly "
    "granularity, group by decade not year. Override only when the user "
    "says 'year', 'yearly', or 'annual'.",

    "release_fact has grain release × style; counts of unique releases use "
    "COUNT(DISTINCT release_id) or query release_unique_view.",
]
```

`rendered_block` and `rendered_token_count` are computed
once at startup and cached so prompt rendering is just a
string substitution, not a re-build.

### Validation rules

- `sample_values` must include `primary_genre`,
  `primary_format_group`, and `decade` for
  `release_unique_view`, plus `style` for `release_fact`,
  whenever those columns/tables are present. `country` is
  optional (top-20 if present).
- The total `rendered_token_count` must be ≤ 600.
- `published_run_id` is read from
  `SELECT MAX(run_id) FROM release_unique_view`. May be NULL
  if the column is absent (older catalogs); the warning is
  logged but does not fail.
- Cache key: process-local. Refreshed only on
  `reset_schema_cache()` (test helper) or process restart.

## 2. agent_runs.status enum (Postgres)

### Existing CHECK constraint

```sql
CHECK (status IN (
  'running','succeeded',
  'failed_safety','failed_validation','failed_unsupported',
  'failed_clarification_needed','failed_internal'
))
```

### New CHECK constraint

```sql
CHECK (status IN (
  'running','succeeded','succeeded_empty',
  'failed_safety','failed_validation','failed_unsupported',
  'failed_clarification_needed','failed_internal'
))
```

### Semantics

- `succeeded` — the sandbox ran, the chart validator passed,
  and `row_count > 0`.
- `succeeded_empty` — **new**. The sandbox ran cleanly, the
  chart validator confirmed the artifact was produced, but
  `row_count == 0`. The user gets a "no matching releases"
  reply with the SQL preserved. The agent does NOT retry
  (zero rows is a valid answer to a question with no
  matches).
- `failed_*` values keep their meaning.

### Migration

Single Alembic revision. Drops and re-adds the named CHECK
constraint. Runs in a single transaction; downtime budget = 0
(both old and new statuses are valid during migration since
the new set is a strict superset).

## 3. chart_validator tool output

### Existing shape (model_dump from `ValidatorOutput`)

```python
class ValidatorOutput(BaseModel):
    valid: bool
    reason: str | None  # e.g., "missing_chart", "row_count_too_high"
    chart_path: str | None
    row_count: int
```

### Extended shape

`valid` keeps its semantics. We add one new `reason`:

```python
reason ∈ {
  None,                  # valid
  "missing_chart",
  "row_count_too_high",
  "empty_result",        # NEW
  "schema_mismatch",
  ...
}
```

`reason="empty_result"` is special: `valid=True` (the
execution succeeded) and the *node* maps it to
`terminal_status="succeeded_empty"`. This avoids a confusing
`valid=False` for what is, technically, a clean run.

## 4. Cross-references

| Where | What |
|---|---|
| `agent/src/discogs_agent/duckdb_layer/schema.py` | The `SchemaContext` extension, sample-values builder, glossary block, token-budget enforcement. |
| `agent/src/discogs_agent/tools/chart_validator.py` | The new `empty_result` reason + `valid=True` semantics. |
| `agent/src/discogs_agent/graph/nodes/chart_validator.py` | Maps `reason="empty_result"` to `terminal_status="succeeded_empty"` and skips retry. |
| `agent/src/discogs_agent/persistence/migrations/versions/005_xx_add_succeeded_empty.py` | Alembic migration extending the CHECK. |
| `agent/src/discogs_agent/prompts/*.md` | Render the new `{sample_values_block}` and `{domain_glossary_block}` placeholders. |
