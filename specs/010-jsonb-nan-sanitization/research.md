# Research: JSONB NaN sanitization

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Three decisions taken during Phase 0. Each states what was chosen, why, what was rejected, and what would change the answer in the future.

---

## R1 — Chokepoint placement

### Decision

A SQLAlchemy `TypeDecorator` wraps the existing `JSONType` (currently `JSONB().with_variant(JSON(), "sqlite")`). The decorator's `process_bind_param` hook calls the sanitizer on every column-write across all five JSONB columns and across both Postgres and SQLite. One chokepoint, no per-call-site discipline.

Resulting shape in `models.py`:

```python
from sqlalchemy.types import TypeDecorator

from .sanitize import sanitize_for_jsonb


class _SanitizedJSON(TypeDecorator):
    """JSONB on Postgres / JSON on SQLite, with NaN/Infinity stripped at write time.

    See specs/010-jsonb-nan-sanitization/contracts/amendment-004-postgres-schema.md
    for the contract this implements.
    """
    impl = JSONB().with_variant(JSON(), "sqlite")
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return sanitize_for_jsonb(value)


JSONType = _SanitizedJSON
```

### Rationale

- **Single site**: every JSONB column inherits the decorator's behavior. Adding a sixth JSONB column in the future automatically gains sanitization.
- **Both dialects covered**: the `TypeDecorator` runs on top of the variant, so SQLite (which silently accepts NaN today) is also sanitized. Test stratum and production are consistent.
- **Read paths unaffected**: `process_bind_param` runs on writes; reads use `process_result_value` which we don't override.
- **No driver coupling**: doesn't touch psycopg's JSON adapter or its `dumps` callable. If the underlying driver changes (psycopg2, asyncpg), the decorator continues to work because it operates above the driver layer.
- **`cache_ok = True`**: the decorator is purely structural; SQLAlchemy's statement cache can reuse compiled statements safely.

### Alternatives considered

| Alternative | Why rejected |
|------------|--------------|
| Sanitize inside each `Repo.create()` method (5 call sites) | Per-call-site discipline. Constitution VII.b-style enforcement would warn against it (the discipline lives in spec, not in the code path). New JSONB columns require remembering to call the sanitizer. |
| SQLAlchemy `before_insert` / `before_update` event hooks on each model | Doesn't fire for raw SQL `INSERT` (none in current code path, but possible). Plus, you have to register a hook per model — more places to forget. |
| Wrap psycopg's JSON adapter to use `allow_nan=False` and let it raise | Promotes silent-bug to fail-loudly at the wire layer, but doesn't fix anything — the run still 500s. We need to *recover* (sanitize) at the boundary, not fail harder. |
| Pre-validate every Pydantic model with a custom `field_validator` that rejects NaN | Promotes the bug upstream, requires per-model discipline, doesn't help non-Pydantic dicts (e.g., `agent_runs.metadata_json` populated from raw dicts). |
| Run `json.dumps(value, allow_nan=False)` at the boundary, catch `ValueError`, sanitize and retry | Slow (double serialization on every clean dict) and complex error-path. Cleaner to sanitize unconditionally — the sanitizer is fast and idempotent. |
| Custom `dumps=` parameter on the `JSON` column | psycopg accepts a custom `dumps` callable, but propagating it through SQLAlchemy's variant chain is awkward. The `TypeDecorator` is simpler and more idiomatic. |

### What would flip this decision

- A future migration to a different ORM that doesn't have `TypeDecorator`. Unlikely.
- A scenario where the sanitizer needs configuration (e.g., "replace NaN with `null` in column A but with `0` in column B"). Then per-Repo would be unavoidable. Out of scope today; not foreseeable.

---

## R2 — Test strategy

### Decision

Two layers, both deterministic, both CI-friendly:

**Layer A — Unit tests for the sanitizer** (`agent/tests/unit/test_jsonb_sanitizer.py`):

Six named cases per FR-010 + SC-005:

1. `test_top_level_nan_replaced_with_none`
2. `test_nested_dict_nan_replaced` (NaN inside dict-inside-dict)
3. `test_nan_inside_list_replaced` (NaN as a list element)
4. `test_positive_and_negative_infinity_replaced` (both `float('inf')` and `float('-inf')`)
5. `test_idempotent_on_clean_input` (run sanitizer twice, output unchanged)
6. `test_does_not_mutate_input` (deep-equality of input pre/post-call)

Plus a small set of "preserves clean values" assertions: regular floats, ints, strings, booleans, None, empty dict/list, deeply-nested clean structure.

**Layer B — Integration test through the persistence boundary** (`agent/tests/integration/test_jsonb_nan_persistence.py`):

Constructs a `ToolCall` row with NaN inside `output_json`, calls `ToolCallRepo.create(...)`, `session.flush()`, `session.expire_all()`, fetches the row back, asserts:
- The flush did not raise.
- The fetched `output_json` does NOT contain any `nan` floats.
- The fetched `output_json` contains `None` at the positions where NaN used to be.
- Regular non-NaN float values are preserved bit-exact.

Runs against the SQLite test stratum (the existing `agent_env` / `db_session` fixture).

### Why no Postgres-fixture test in CI

The user-facing failure is Postgres-only — SQLite silently accepts NaN. So a SQLite-only test technically doesn't exercise the production failure mode end-to-end. However:

- **Sanitizer correctness**: Layer A covers it deterministically.
- **Boundary integration**: Layer B confirms the sanitizer fires at the persistence boundary (read-back returns `None`, not the original NaN — proving the `process_bind_param` hook ran).
- **Postgres-only concerns**: there's nothing the SQLite test misses except "Postgres rejects, would the unsanitized data crash here?" — and we know it does (the user's stack trace is the proof).

A Postgres-fixture variant is documented as a stretch in `quickstart.md` for manual local verification. It's not gated by CI because:
- The project's existing test suite uses SQLite for speed and reproducibility.
- Adding a Postgres fixture pulls in `testcontainers` or equivalent infra — disproportionate for this size of change.
- The manual SC-001/SC-002 gates against the live stack provide the production-faithful confirmation.

### Alternatives considered

| Alternative | Why rejected |
|------------|--------------|
| Skip Layer B; rely on Layer A only | Layer B is the proof that the chokepoint actually fires. Without it, a future refactor that drops the `TypeDecorator` would slip through Layer A. |
| Add a Postgres fixture via `testcontainers` to CI | Slow (~30s startup), pulls in Docker dependency for tests, disproportionate for a 30-LOC fix. Not how the rest of the test suite is structured. |
| Mock `psycopg.errors.InvalidTextRepresentation` and assert the sanitizer prevents it | Layers a brittle mock on top of a real boundary. The real test (write through SQLAlchemy + read back) is straightforward and uncoupled from psycopg internals. |
| Snapshot-test the sanitizer output against a recorded golden | Overkill — the sanitizer's contract is a tight invariant, not a long string. Six named assertions are clearer than a golden file. |

### What would flip this decision

- A bug class that surfaces only on Postgres (not SQLite). At that point, adding a Postgres fixture becomes worthwhile and we'd land it as part of that bug's fix.

---

## R3 — Sanitizer signature & implementation

### Decision

```python
# agent/src/discogs_agent/persistence/sanitize.py
from __future__ import annotations

import math
from typing import Any


def sanitize_for_jsonb(value: Any) -> Any:
    """Replace NaN/Infinity floats with None recursively.

    Pinned by specs/010-jsonb-nan-sanitization/. Returns a new value;
    does NOT mutate the input. Idempotent on clean inputs. Recurses
    through dicts, lists, and tuples (tuples become lists).

    Cost: O(n) where n is the number of leaf values. Negligible for
    the dict sizes typical at the persistence boundary (tens of KB).
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: sanitize_for_jsonb(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_jsonb(item) for item in value]
    return value
```

### Rationale

- **Stdlib only**: `math.isnan` and `math.isinf` are the standard checks. `math.isfinite` would also work but is redundant when we're explicitly testing two conditions.
- **`isinstance(value, float)` at the top**: `bool` is a subclass of `int` (not `float`), so booleans aren't mishandled. `bool` falls through to the final `return value` branch.
- **Tuples → lists**: per FR-004, tuples are uncommon in this code path; converting them mirrors what `json.dumps` would do anyway.
- **Pure function**: returns a new dict/list at every level. Original input is untouched (FR-005).
- **Idempotent**: applied to a clean dict, every leaf passes through `return value`; applied to a NaN-containing dict, NaN becomes `None` and a second application sees `None` (which falls through to `return value`).
- **No special-case for `numpy` types**: pandas-via-`to_dict` returns Python `float`s by default. If a `numpy.float64('nan')` ever surfaced, `math.isnan` would still catch it (numpy scalars implement `__float__`). The test suite doesn't synthetically produce numpy values; the production reproducer uses pandas → dict which yields native floats.
- **No `bytes` / `set` / `Decimal` handling**: those types aren't expected at the persistence boundary (Pydantic `model_dump()` produces only the JSON-compatible primitives + dict/list). Defensive: they'd fall through to `return value` and SQLAlchemy would reject them downstream — surfacing the issue rather than silently corrupting the data.

### Alternatives considered

| Alternative | Why rejected |
|------------|--------------|
| Use `pandas.io.json.dumps(value, default=...)` | Adds pandas import to the persistence layer; pandas already isn't imported there (it lives in the sandbox path). Tighter to use stdlib. |
| Use `json.dumps(value, allow_nan=False)` to detect NaN, then post-process the JSON string | Stringly-typed; invites edge cases (numbers in scientific notation, unicode escaping). Recursive Python-side processing is cleaner. |
| Use `simplejson` with `ignore_nan=True` | Adds a dependency for a stdlib-solvable problem. |
| Replace NaN with the string `"NaN"` (or `0`) instead of `None` | `None` → JSON `null` is the standard semantic for missing data. The whole point is to preserve the "this cell was missing" signal. Substituting a non-null sentinel would surprise downstream consumers. |
| Mutate the input in place to avoid the allocation | Saves O(n) allocations but breaks FR-005 and adds debugging surprises. The input often comes from a Pydantic `model_dump()` and the caller expects to be able to use it after. Allocations at this scale are free. |

### What would flip this decision

- A persistence path that legitimately wants to preserve NaN as a sentinel (no such path exists in V1 or any planned feature).
- A performance regression caused by the recursion (we'd cap recursion or use iterative). Theoretical; the typical tool-call dict is shallow.

---

## Cross-decision invariants

- **One chokepoint = one import**. The sanitizer is imported only from `agent/src/discogs_agent/persistence/models.py`. SC-006 verifies this with grep.
- **Tests don't use real psycopg**. Layer B uses the existing `db_session` fixture (SQLite). The unit-level sanitizer tests don't touch any DB at all. CI stays fast.
- **Production rows unchanged**. The fix only touches write paths. All existing rows that successfully wrote pre-fix are by definition already standards-compliant; the sanitizer is a no-op on read.
- **Backwards compatibility on the public API**: `JSONType` keeps the same import path and the same observable behavior for clean dicts. Consumers see no difference unless their dict contains NaN (in which case they used to crash and now don't).
