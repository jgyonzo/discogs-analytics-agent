# Contract: Sandbox `exception_type` taxonomy (canonical set)

**Source feature**: `013-filtered-aggregation-postmortem`
**Owner**: `agent/src/discogs_agent/sandbox/runner.py` (producer); `agent/src/discogs_agent/tools/chart_validator.py` + downstream consumers.
**Status**: normative.

This contract pins the canonical set of `exception_type` values that flow out of the sandbox runner. The pre-013 taxonomy was implicit in code; 013 makes it contractual.

---

## Allowed values

Exhaustive list. Implementations MUST emit one of these or `None` (clean success). Adding a new value is a contract amendment.

| Value | Producer | Trigger condition | `exception_message` shape |
|-------|----------|-------------------|---------------------------|
| `None` | clean path | `exit_code == 0` AND RESULT extracted successfully | n/a |
| `"timeout"` | harness wall-clock watchdog | `subprocess.TimeoutExpired` caught at `runner.py:107` | `"timeout"` (or empty) |
| `"parse_failed"` | RESULT extractor | RESULT markers found in stdout but JSON-decode failed | the underlying `json.JSONDecodeError` message |
| `"no_result"` | RESULT extractor | `exit_code == 0` but no RESULT markers in stdout | `None` |
| `"nonzero_exit"` | catch-all fallthrough | `exit_code > 0` AND `exception_type` still `None` after RESULT extraction (positive non-zero exits — e.g., `sys.exit(1)`) | `"exit_code={n}"` |
| `"oom_killed"` | **NEW (013)** | `exit_code == -9` AND `exception_type` still `None` after RESULT extraction — i.e., external SIGKILL, NOT the harness's own timeout path (which sets `exception_type` to `"timeout"` before the catch-all fires) | `"kernel SIGKILL (cgroup OOM-killer); exit_code=-9; sandbox exceeded memory budget"` |
| `"sandbox_signaled"` | **NEW (013)** | `exit_code < 0` AND `exit_code != -9` AND `exception_type` still `None` (other signal kills: SIGSEGV/-11, SIGABRT/-6, SIGTERM/-15, …) | `"sandbox killed by signal {n}; exit_code={exit_code}"` where `n = -exit_code` |
| `<exception class name>` | Python script raised an exception inside the sandbox | extracted from the sandbox payload's `_error` field via `runner.py:129` | the exception's stringified message |

---

## Mapping from `exit_code` to `exception_type`

Implementations MAY use this decision table verbatim:

```python
def derive_exception_type(
    exit_code: int,
    harness_timeout_fired: bool,
    parsed_error: str | None,  # from RESULT block's _error field
    parse_succeeded: bool,     # RESULT markers found and JSON-decoded
) -> tuple[str | None, str | None]:
    """Returns (exception_type, exception_message)."""

    # 1. Harness's own timeout path — set BEFORE the catch-all.
    if harness_timeout_fired:
        return ("timeout", "")

    # 2. Python-side exception bubbled through the RESULT envelope.
    if parsed_error:
        return (parsed_error, "")  # exception class name + message

    # 3. RESULT shape problems.
    if exit_code == 0 and not parse_succeeded:
        return ("no_result", None)

    # 4. Signal kills (negative exit codes on POSIX).
    if exit_code == -9:
        return (
            "oom_killed",
            "kernel SIGKILL (cgroup OOM-killer); "
            "exit_code=-9; sandbox exceeded memory budget",
        )
    if exit_code < 0:
        signal_num = -exit_code
        return (
            "sandbox_signaled",
            f"sandbox killed by signal {signal_num}; exit_code={exit_code}",
        )

    # 5. Positive non-zero exit (script ran sys.exit(n) or similar).
    if exit_code != 0:
        return ("nonzero_exit", f"exit_code={exit_code}")

    # 6. Clean success.
    return (None, None)
```

The runner's actual implementation is free to be more structurally similar to the existing code; this decision table is the *semantic* spec.

---

## Why the OOM-vs-signaled split is "two values, not one umbrella, not five"

- **SIGKILL is the OOM signature in this cgroup.** The only producer of `-9` outside the harness's own timeout path is the kernel OOM-killer. The harness uses `os.killpg(..., signal.SIGKILL)` at `runner.py:102`, but always sets `exception_type = "timeout"` first (line 108). The catch-all branch only fires when neither the harness nor a Python exception set the type — which leaves the OOM-killer as the only realistic producer for `-9`.
- **Other signals are rare and don't have a single dominant cause.** SIGSEGV typically means a C-level bug in a dependency (DuckDB, Arrow, libfoo). SIGABRT typically means an assertion. SIGTERM is unusual in this runtime. Lumping them under `"sandbox_signaled"` with the signal number in the message is honest: downstream code that genuinely needs to branch on SIGSEGV can parse it out of the message string.
- **Naming each individual signal would over-fit** to incidents we haven't seen yet. If a recurring SIGSEGV class appears, that's the trigger to amend this contract with a `"sigsegv"` value — driven by data, not speculation.

---

## Downstream consumers of `exception_type`

Implementations MUST honor the following downstream dispatch rules. Each rule is named here and enforced in the consumer's own contract / code:

| Consumer | Rule for new values | FR |
|----------|---------------------|----|
| `chart_validator` | `exception_type == "oom_killed"` short-circuits the legacy three-error layering (`nonzero_exit` + `exception_raised` + `result_missing`) and emits exactly one `ValidationError(rule="oom_killed", detail=<exception_message>)`. `exception_type == "sandbox_signaled"` keeps the legacy layering (insufficient information to specialize). | FR-002 |
| `response_synthesizer._build_result_block` | When `validation_result.errors[]` contains a rule of `"oom_killed"`, append the diagnostic hint from `research.md §R3` to the result_block. Other new values do NOT trigger this; they fall through to the existing fallback. | FR-003 |
| `code_generator._format_failures` | No change. The function already surfaces `exception_type` + `exception_message` into the repair prompt's `{failure_details}` slot. The LLM gets the named cause for free. | FR-004 (no-op) |
| `cost_logger` / `agent_tool_calls.output_json` persistence | No change. The new values serialize through the existing JSON column without schema changes. | n/a |

---

## Determinism guarantee (FR-005)

`derive_exception_type` MUST be a pure function of its inputs. No randomness, no env-variable reads, no time-dependent behavior. The same `(exit_code, harness_timeout_fired, parsed_error, parse_succeeded)` tuple MUST produce the same `(exception_type, exception_message)` tuple on every invocation.

This guarantee is what makes the new values *safe to dashboard on*: a dashboard query like `SELECT COUNT(*) FROM agent_tool_calls WHERE output_json ->> 'exception_type' = 'oom_killed'` is meaningful exactly because the value space is closed and deterministic.

---

## Backward compatibility

- All pre-013 values (`None`, `"timeout"`, `"parse_failed"`, `"no_result"`, `"nonzero_exit"`, Python exception class names) are preserved with identical semantics.
- The only semantic narrowing: pre-013, `"nonzero_exit"` covered `exit_code == -9`. Post-013, that case is reassigned to `"oom_killed"`. Any historical dashboard that filtered on `exception_type = 'nonzero_exit'` AND `exit_code = -9` will need to update its query — but the same predicate runs against the new value space.
- Historical `agent_tool_calls` rows are NOT backfilled (per `spec.md` Out-of-Scope). The new values apply prospectively.

---

## Unit-test coverage (FR-001 test side)

A new test module `agent/tests/unit/test_sandbox_signal_mapping.py` MUST exercise:

1. `exit_code=-9` + `harness_timeout_fired=False` + `parsed_error=None` → `("oom_killed", <non-empty message>)`.
2. `exit_code=-9` + `harness_timeout_fired=True` → `("timeout", _)` (preserves harness path; FR-001 explicit-not-regress).
3. `exit_code=-11` + `harness_timeout_fired=False` + `parsed_error=None` → `("sandbox_signaled", <message containing "signal 11">)`.
4. `exit_code=1` + `harness_timeout_fired=False` + `parsed_error=None` → `("nonzero_exit", "exit_code=1")` (preserves positive-non-zero path).
5. `exit_code=0` + `parsed_error="BinderError"` → `("BinderError", _)` (preserves Python-exception path).

---

## Constitution compliance

- **VII.a** (Configuration sources): the string literals `"oom_killed"` and `"sandbox_signaled"` are taxonomy constants, not configuration. They MUST NOT be env-driven or settings-driven.
- **VII.c** (Read-only runtime mechanics): this contract is the symmetric observability analog. The runtime constraint (`:ro` mount, cgroup memory cap) has been declared since 004; 013 declares the *failure surface* the constraint produces when reached.
- **Principle VI** (Two Components, One Contract): producer and all consumers live entirely within `agent/`. ETL component is not touched.
