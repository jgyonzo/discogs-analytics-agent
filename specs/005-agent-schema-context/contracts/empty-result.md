# Contract: Empty-Result Handling

## Statuses

`agent_runs.status` after this feature lands:

| Status | Meaning |
|---|---|
| `running` | Run is in flight. |
| `succeeded` | Sandbox ran, chart validator passed, `row_count > 0`. |
| `succeeded_empty` | **NEW.** Sandbox ran, chart validator passed structurally, `row_count == 0`. User gets a "no matches" reply with the SQL preserved. |
| `failed_safety` | Two-pass safety check rejected the SQL after retries. |
| `failed_validation` | Chart validator failed (bad shape) after retries. |
| `failed_unsupported` | Router classified the question as outside the data surface. |
| `failed_clarification_needed` | Router asked for clarification. |
| `failed_internal` | Catch-all. |

## chart_validator tool — output additions

Existing `ValidatorOutput.reason` set is extended with one
value: `"empty_result"`.

```python
ValidatorOutput(
    valid=True,                # NB: True, not False
    reason="empty_result",
    chart_path=<existing_path>,
    row_count=0,
)
```

`valid=True` is intentional — the sandbox ran cleanly and the
chart artifact was produced. The reason field carries the
distinguishing signal for the *node* and downstream consumers.

## chart_validator node — branch logic

```python
def chart_validator_node(state: AgentState) -> AgentState:
    ...
    if result.valid and result.reason == "empty_result":
        state["validation_result"] = result.model_dump()
        state["terminal_status"] = "succeeded_empty"
        return state

    # existing path (valid, retry, give-up) unchanged
```

```python
def validation_edge(state: AgentState) -> str:
    validation = state.get("validation_result") or {}
    if state.get("terminal_status") == "succeeded_empty":
        return "response_synthesizer"
    if validation.get("valid"):
        return "response_synthesizer"
    if validation.get("should_retry"):
        return "code_generator"
    state["terminal_status"] = "failed_validation"
    return "response_synthesizer"
```

The empty-result path skips retry — re-running the same SQL
will return the same zero rows. The user has to rephrase.

## response_synthesizer — message shape

When `terminal_status == "succeeded_empty"`, the synthesizer
prompt receives a `result_block` that includes:

- The SQL that ran (already present today).
- A literal "no matching releases" line.
- A one-line diagnostic hint: *"if you were filtering by a
  musical style (e.g., Techno, House), check the schema
  context — that style might be a `style` value, not a
  `primary_genre`."*

The synthesizer returns plain prose; no chart-artifact pointer
is included in the user-visible body. The artifact file may
still exist on disk (the sandbox produced it before
chart_validator ran) but the API response sets
`chart_artifact: null` for empty-result runs.

## API response (FastAPI `/query`)

`response.status` value `succeeded_empty` is added.
`response.chart_artifact` MUST be `null`.
`response.dataframe_preview` MUST be `[]`.
`response.row_count` MUST be `0`.
`response.sql` echoes the SQL that ran.
`response.code` echoes the generated Python (already present).
`response.response` (the user-visible text) is the synthesizer's
"no matching releases" message.

This shape is forward-compatible with current API consumers
that read `status` as an opaque enum.

## Test coverage

- Unit: `tests/unit/test_chart_validator.py` extended with a
  fixture where the sandbox returns `row_count=0`. Asserts
  `valid=True`, `reason="empty_result"`, and the node sets
  `terminal_status="succeeded_empty"` with no retry.
- Golden: a query for a known-empty filter (e.g., a
  hallucinated style "Polka") asserts the API response
  matches the shape above.
