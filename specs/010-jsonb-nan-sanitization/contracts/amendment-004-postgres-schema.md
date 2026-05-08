# Amendment to `004/contracts/postgres-schema.md` — JSONB input invariant

**Source feature**: `010-jsonb-nan-sanitization`
**Target file**: `specs/004-agent-v1/contracts/postgres-schema.md`
**Insert as**: a new top-level section "## 7. JSONB input invariant" placed AFTER the existing "## 6. Backward-compat & seeds" and BEFORE the document's end.

This is the exact prose to land in `004/contracts/postgres-schema.md` in the same change set as the agent code change (the `_SanitizedJSON` `TypeDecorator` in `agent/src/discogs_agent/persistence/models.py` plus the new `agent/src/discogs_agent/persistence/sanitize.py`). Mirrors 007's amendment to `004/contracts/code-generation.md` and 009's amendment to `005/contracts/schema-context.md`.

---

## Insertion: New section "## 7. JSONB input invariant"

```markdown
## 7. JSONB input invariant

*Added 2026-05-08 by `010-jsonb-nan-sanitization`. Closes a
silent-class failure where a dataframe-preview row containing
`float('nan')` (pandas's representation of a NULL cell) caused
Postgres to reject the JSONB write with
`InvalidTextRepresentation: Token "NaN" is invalid`. Named
incident: run `4b0f6979-71f8-41dc-8d79-204933621f3a`,
question "What are the top 15 countries by number of releases?".*

### 7.1 The constraint

Postgres `JSONB` columns enforce RFC-8259 — the strict JSON spec.
The following are NOT valid JSON and Postgres rejects them at the
wire level:

- `NaN`
- `Infinity`
- `-Infinity`

Python's stdlib `json.dumps` is `allow_nan=True` by default and
emits these tokens. psycopg's default JSON adapter uses
`json.dumps`. Pandas dataframes routinely produce `float('nan')`
for NULL cells; Pydantic `model_dump()` preserves them.

Therefore: **every dict written into a JSONB column MUST be
RFC-8259-compliant before SQLAlchemy `flush()`**. This is a hard
invariant the wire-protocol enforces; the agent's persistence
layer guarantees it at the boundary.

### 7.2 The five JSONB columns

Per §1 of this contract, the JSONB-typed columns are:

| Table | Column |
|-------|--------|
| `agent_runs` | `metadata_json` |
| `agent_threads` | `metadata_json` |
| `agent_tool_calls` | `input_json` |
| `agent_tool_calls` | `output_json` |
| `agent_artifacts` | `metadata_json` |

The invariant applies to all five.

### 7.3 The chokepoint

The agent enforces §7.1 at exactly one place: a SQLAlchemy
`TypeDecorator` wrapping `JSONType`
(`agent/src/discogs_agent/persistence/models.py`). The decorator's
`process_bind_param` hook applies the sanitizer
(`agent/src/discogs_agent/persistence/sanitize.py`) to every
column-write before the value reaches the driver.

Per-call-site sanitization (e.g., inside each `Repo.create`
method) is **explicitly forbidden** as the primary enforcement
mechanism — it would turn the invariant into discipline rather
than mechanism. Per-call-site checks MAY exist as additional
defense-in-depth, but the load-bearing enforcement is the
`TypeDecorator`.

### 7.4 The sanitizer's contract

The sanitizer is a pure function with the following contract:

- **Signature**: `sanitize_for_jsonb(value: Any) -> Any`.
- **Behavior on numerics**: `float('nan')`, `float('inf')`, and
  `float('-inf')` are replaced with `None`. All other floats,
  ints, and booleans pass through unchanged.
- **Behavior on containers**: `dict`, `list`, and `tuple` are
  recursed into. Tuples become lists (matching `json.dumps`'s
  default behavior). Sets, bytes, and other non-JSON-native
  types are NOT special-cased — they fall through and downstream
  serialization will reject them, surfacing rather than hiding
  unexpected types.
- **Idempotence**: applied twice, output equals applied once.
- **Mutation-freedom**: the input is never modified. The function
  returns a new value at every container level.
- **Cost**: O(n) where n is the number of leaf values.
  Negligible for the dict sizes at this boundary (tens of KB).

### 7.5 Backwards compatibility

- `JSONType` keeps the same import path (`from .models import
  JSONType`). Consumers see no difference for clean dicts.
- All existing rows in production Postgres are already
  RFC-8259-compliant (the bug *prevented* writes; it never
  produced corrupt rows). No retroactive cleanup is needed.
- SQLite (test stratum) gains the same sanitization. Pre-amendment,
  SQLite silently accepted NaN floats because Python's default
  encoder writes them. Post-amendment, SQLite and Postgres are
  consistent: writes produce the same JSON shape on both.

### 7.6 What this invariant does NOT do

- **Does not validate upstream code paths**. Sandboxes, generated
  code, and Pydantic models continue to be free to use NaN as a
  missing-data sentinel internally. The boundary is the only
  place where standards-compliance is enforced.
- **Does not promote a NaN read-back contract**. Read paths return
  whatever Postgres stored, which is RFC-8259 JSON. Consumers see
  `None` (Python) / `null` (JSON) at positions where the original
  data had NaN. This is a one-way conversion: NULL semantics are
  preserved; NaN-as-arithmetic-sentinel semantics are not (and
  shouldn't be — the persistence layer doesn't carry computational
  state).
- **Does not guard against other RFC-8259 violations** beyond
  NaN/Infinity. UTF-8 invalidity, circular references, or
  `Decimal` types would still trip the wire layer; those are
  out of scope for this amendment because they don't have a known
  reproducer in the agent's V1 code paths. If future code paths
  produce them, a separate amendment can extend the sanitizer.

### 7.7 Disciplinary analog (Constitution VII.c)

This invariant is the **write-side counterpart** to the read-side
mechanics established by Constitution VII.c
(`.specify/memory/constitution.md`). VII.c says: "When a runtime
constraint declares a resource read-only, the constraint's
*consequences* MUST be documented alongside it." This amendment
applies the symmetric statement to a write target: Postgres JSONB
declares "RFC-8259-compliant JSON only," and that constraint's
*consequences* (NaN floats from upstream code paths) are
documented and mitigated alongside it. The 010 spec frames this
as a follow-through; no constitution amendment is required.

### 7.8 Verification

Pinned by:

- `agent/tests/unit/test_jsonb_sanitizer.py` — unit-level tests
  for the sanitizer's contract (FR-001..FR-005, FR-008,
  SC-005).
- `agent/tests/integration/test_jsonb_nan_persistence.py` —
  end-to-end test through `ToolCallRepo.create` against the
  SQLite test stratum (FR-011, SC-003).
- Manual smoke against the live Postgres stack via
  `specs/010-jsonb-nan-sanitization/quickstart.md` (SC-001,
  SC-002).
```

---

## Why amend `004` rather than create a new `010/contracts/postgres-schema.md`

Same reasoning as 007 amending `004/contracts/code-generation.md` and 009 amending `005/contracts/schema-context.md`:

- The Postgres schema and persistence layer are a single contract surface owned by `004`. Splitting it across multiple specs would force readers to chase the JSONB invariant through the spec history.
- The "JSONB input invariant" is not a *new* contract surface; it's a property of the existing JSONB columns.
- This pattern keeps `004/contracts/postgres-schema.md` the single source of truth for "what the agent's persistence layer enforces" — consistent with how 007 kept `004/contracts/code-generation.md` the single source of truth for "what the sandbox enforces."

## Implementation pointer

The amendment lands together with:

- `agent/src/discogs_agent/persistence/sanitize.py` (new) — the pure `sanitize_for_jsonb` function per research §R3.
- `agent/src/discogs_agent/persistence/models.py` — replace the `JSONType = JSONB().with_variant(JSON(), "sqlite")` line with a `_SanitizedJSON(TypeDecorator)` class whose `impl` is the existing variant chain and whose `process_bind_param` calls `sanitize_for_jsonb`. Export `JSONType = _SanitizedJSON` so all existing column declarations (lines 84, 117, 159, 160, 226 per the current file) continue to work without edits.
- `agent/tests/unit/test_jsonb_sanitizer.py` (new) — 6 named cases per research §R2 Layer A.
- `agent/tests/integration/test_jsonb_nan_persistence.py` (new) — boundary integration test per research §R2 Layer B.

No new dependencies. No prompt-template edits. No DDL change (`JSONB` and `JSON` column types at the database layer are unchanged — only the SQLAlchemy-side wrapping changes).
