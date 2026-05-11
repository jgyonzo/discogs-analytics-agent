# Data Model: 013-filtered-aggregation-postmortem

**Date**: 2026-05-10
**Scope**: this feature is *taxonomic*, not data-shaped. No new tables, columns, or persisted entities are introduced. The artifacts that change are runtime values flowing through existing JSON-blob columns in Postgres and existing in-process state in LangGraph. This document enumerates those artifacts and their new value sets — strictly for cross-reference from `contracts/` and `tasks.md`. Read it as a glossary of state shapes, not a database schema.

---

## Entity 1: `SandboxOutcome.exception_type`

**Location**: `agent/src/discogs_agent/sandbox/runner.py:37` (dataclass field) → serialized into `agent_tool_calls.output_json` for the `sandbox_executor` row.

**Type**: `str | None`.

**Pre-013 value set** (from `004/contracts/code-generation.md §3.4` + observed code):

| Value | Producer | Meaning |
|-------|----------|---------|
| `None` | clean success | RESULT is present, `exit_code == 0` |
| `"timeout"` | harness wall-clock timeout fires `subprocess.TimeoutExpired` | sandbox process SIGKILL'd by harness after `settings.SANDBOX_TIMEOUT_SECONDS` |
| `"parse_failed"` | `runner.py:123` | RESULT markers found but JSON-decode failed |
| `"no_result"` | `runner.py:145` | script exited cleanly but no RESULT markers |
| `"nonzero_exit"` | `runner.py:137–138` catch-all | `exit_code != 0` and nothing else set `exception_type` |
| `<exception class name>` (e.g., `"BinderError"`, `"KeyError"`) | `runner.py:129`, extracted from sandbox payload `_error` field | Python raised inside the sandboxed script |

**Post-013 value set** (additions):

| Value | Producer | Meaning |
|-------|----------|---------|
| `"oom_killed"` | new branch inside `runner.py:137` fallthrough | `exit_code == -9` AND `exception_type is None` at the catch-all — i.e., external SIGKILL not initiated by the harness itself. In practice, the kernel cgroup OOM-killer. `exception_message` carries the explanatory string from R1. |
| `"sandbox_signaled"` | same branch as above | `exit_code < 0` AND `exit_code != -9` AND `exception_type is None`. `exception_message` includes the signal number. |

The pre-existing `"nonzero_exit"` value is retained for `exit_code > 0` (positive non-zero exits — i.e., the script exited cleanly with a non-zero return code via `sys.exit(n)` or similar, NOT a signal kill). After 013, the catch-all naturally splits into two branches: positive non-zero → `"nonzero_exit"`; negative → signal-aware.

**Determinism (FR-005)**: pure function of `(exit_code, harness_timeout_fired_flag)`. No randomness, no env-variable input.

**Contractual surface**: `specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md` is the source-of-truth document. `specs/004-agent-v1/contracts/code-generation.md §3.4` is the consumer table that references it.

---

## Entity 2: `ValidationError` (chart_validator output)

**Location**: `agent/src/discogs_agent/tools/chart_validator.py` returns a list of these inside `ValidationResult.errors`. Serialized into `agent_tool_calls.output_json` for the `chart_validator` row.

**Shape** (pre- and post-013):

```python
class ValidationError:
    rule: str       # short identifier
    detail: str     # human-readable explanation
```

**Pre-013 rule values** (relevant to the OOM path):

| Rule | When emitted | Producer line |
|------|--------------|---------------|
| `"nonzero_exit"` | `er.get("exit_code") != 0` | `chart_validator.py:58–63` |
| `"exception_raised"` | `er.get("exception_type")` is truthy | `chart_validator.py:65–69` |
| `"result_missing"` | RESULT is None | `chart_validator.py:75` |

For an OOM-killed run, all three fire layered on top of each other — which is what the Depeche Mode trace produced.

**Post-013 rule values** (additions):

| Rule | When emitted | Producer |
|------|--------------|----------|
| `"oom_killed"` | `er.get("exception_type") == "oom_killed"` | new branch in `chart_validator.py` (FR-002), emitted *instead of* the three legacy rules. The `detail` field carries the `exception_message` from the runner. |

The legacy three-rule layering remains for genuinely unknown failures (positive non-zero exit, Python exception class names, etc.) — the OOM short-circuit only specializes the SIGKILL/OOM case.

**Cross-reference**: this entity does not have its own contract doc. Its taxonomy is documented inline in `004/contracts/code-generation.md §3.4` (column 4 of the failure-modes table).

---

## Entity 3: Glossary entry #3 (rendered)

**Location**: `agent/src/discogs_agent/duckdb_layer/schema.py` — `_DOMAIN_GLOSSARY` tuple, entry index 2 (zero-indexed) / item #3 in the numbered rendered list. Rendered into the `{schema_context_block}` substring of every code-generation and repair prompt. Also stored verbatim in `agent_tool_calls.input_json` for the `dataset_schema_reader` row.

**Type**: human-readable Markdown-ish string, rendered as numbered list item `3) …`.

**Pre-013 text** (from 012 amendment, currently deployed):

```text
3) release_fact has grain release × style. For counts of unique
   releases, use `SELECT X, COUNT(DISTINCT release_id) FROM
   release_fact GROUP BY X` — this only tracks per-X distinct
   sets and is cheap. DO NOT use release_unique_view for
   catalog-wide aggregations: the view is defined as
   `SELECT DISTINCT (~33 columns) FROM release_fact` and forces
   DuckDB to materialize the entire deduplicated set (~19M rows
   × 33 cols), which spills GBs of temp even for trivial
   GROUP BYs. release_unique_view is fine for spot-check queries
   against a single release (e.g., `WHERE release_id = N`),
   but never for catalog-wide GROUP BYs. Never use `COUNT(*)
   FROM release_fact` for release counts (it counts release ×
   style rows, not releases).
```

**Post-013 text**: see `research.md §R5` for the exact replacement.

**Invariant**: the text MUST appear byte-equivalent in three locations:

1. `agent/src/discogs_agent/duckdb_layer/schema.py` `_DOMAIN_GLOSSARY` tuple element #3 (deployed source of truth).
2. `agent/tests/integration/golden/schema_context_block.txt` (regenerated golden — locks the deployed text).
3. `specs/005-agent-schema-context/contracts/schema-context.md` glossary entry #3 example block (contract documentation).

Mirroring shorter versions live in `code_generator.md:11–15` and `repair_code.md:37–42` — these are paraphrases per Constitution VII.b carve-out, not byte-equivalent.

---

## Entity 4: Repair-prompt `failure_details` interpolation

**Location**: assembled at `agent/src/discogs_agent/graph/nodes/code_generator.py:91–108` (function `_format_failures`); injected into `repair_code.md` via the `{failure_details}` placeholder.

**Shape**: list of strings, one per failure source. The execution-result branch produces:

```text
Sandbox exception: <exception_type>: <exception_message>
```

**Pre-013 observed output for an OOM-killed run**:

```text
Sandbox exception: nonzero_exit: exit_code=-9
```

**Post-013 observed output for the same run**:

```text
Sandbox exception: oom_killed: kernel SIGKILL (cgroup OOM-killer); exit_code=-9; sandbox exceeded memory budget
```

**Invariant**: FR-004 is satisfied without any code change in this function — only the source value (`exception_type` from FR-001) changes. The LLM-facing surface is the unchanged `{failure_details}` placeholder in `repair_code.md`.

---

## Entity 5: `final_response` (Postgres-persisted user-facing string)

**Location**: `agent_runs.final_response` (NULLABLE TEXT). Written by the response_synthesizer node from the LLM's prose output (`response_synthesizer.py:88`).

**Shape**: free-form string. Pre-013 OOM-killed runs produce the canned synthesizer fallback: *"I generated code but couldn't produce a valid chart after retrying. Try rephrasing your question."*

**Post-013 expected shape for OOM-killed runs**: includes one or more of the substrings `"memory"`, `"too heavy"`, `"narrow your question"`, `"reduce scope"`. The exact prose is LLM-paraphrased from the diagnostic hint in `_build_result_block`'s new branch (see R3); SC-006 verifies via substring search.

**Producer of the upstream signal**: `response_synthesizer.py:_build_result_block`'s new `elif` branch (FR-003) — detects `oom_killed` in `validation_result.errors[]` and appends the hint to the prompt's `{result_block}` interpolation.

---

## Entity 6: Q1 description line

**Location**: `specs/008-agent-frontend-v1/contracts/curated-questions.md` line 18.

**Shape**: a single Markdown bullet line: `- **description**: \`<string>\``.

**Pre-013 value**: `Basic decade-grain trend using release_unique_view.`

**Post-013 value**: `Basic decade-grain release count using COUNT(DISTINCT release_id) FROM release_fact GROUP BY decade.`

This is the only mutable contract surface in `008/` that 013 touches. No frontend code is affected; the description is consumed by humans reading the contract, not by tests or runtime.

---

## What is explicitly NOT a data-model entity in 013

For clarity and to prevent future readers from chasing ghosts:

- **No new database tables** — Postgres schema is untouched.
- **No new columns** — `agent_runs`, `agent_tool_calls`, `agent_model_usage` shapes are unchanged. The new exception_type values flow through existing JSON columns.
- **No new DuckDB tables/views** — the published DuckDB contract is untouched. FR-015's deferral of the view's materialization fix means 013 does NOT alter `release_unique_view`'s definition or any other ETL output.
- **No new LangGraph state keys** — `AgentState` is unchanged. The new exception_type values are already-supported strings flowing through the existing `execution_result["exception_type"]` key.
- **No new prompt placeholders** — the `{failure_details}` slot in `repair_code.md` is reused as-is (R4); the `{result_block}` slot in `response_synthesizer.md` is reused as-is (R3). No template variables are added.

---

## Validation rules from spec requirements

| Spec FR | Validation rule | Entity affected |
|---------|----------------|-----------------|
| FR-005 | `exception_type` mapping is deterministic in `(exit_code, harness_timeout_fired)` | Entity 1 |
| FR-007 | Glossary text MUST contain a clause preserving the `WHERE release_id = <literal>` carve-out | Entity 3 |
| FR-010 | Three byte-equivalence locations for glossary entry #3 (schema.py, golden, contract) | Entity 3 |
| FR-002 | OOM short-circuit emits exactly one rule, not three | Entity 2 |
| FR-003 | `final_response` for OOM-killed runs contains a memory-pressure substring | Entity 5 |

## State transitions

The only "state transition" relevant to this feature is the lifecycle of a single agent run, with two new terminal flavors:

```text
sandbox_executor → exit_code=-9 (external SIGKILL) →
  runner.py catch-all detects exit_code < 0, exception_type is None →
  sets exception_type="oom_killed" →
chart_validator → detects exception_type="oom_killed" →
  emits ValidationError(rule="oom_killed", detail=<exception_message>) →
response_synthesizer → _build_result_block detects oom_killed in errors[] →
  appends diagnostic hint to result_block →
  LLM paraphrases into final_response containing memory-pressure language →
agent_runs.status = "failed_validation" (unchanged terminal status; FR-003 changes the message, not the status)
```

No other state transitions are introduced or modified by 013.
