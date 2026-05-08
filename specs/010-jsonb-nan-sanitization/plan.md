# Implementation Plan: JSONB NaN sanitization

**Branch**: `010-jsonb-nan-sanitization` | **Date**: 2026-05-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-jsonb-nan-sanitization/spec.md`

## Summary

Add a sanitizer at the persistence-write boundary that recursively replaces `float('nan')`, `float('inf')`, and `float('-inf')` with `None` in any dict written to a JSONB column. Single chokepoint via a SQLAlchemy `TypeDecorator` wrapping `JSONType` so all five JSONB columns are covered. Add a regression test (unit-level for the sanitizer; integration-level through `ToolCallRepo.create` against the SQLite test stratum). Amend `004/contracts/postgres-schema.md` with a new §7 declaring the JSONB input invariant.

The fix is small (~30 LOC + ~120 LOC of tests + ~50 lines of contract amendment). The contract amendment is the load-bearing artifact: it makes the boundary discipline visible to the next contributor.

## Technical Context

**Language/Version**: Python 3.12 (existing agent runtime).
**Primary Dependencies**: existing — `sqlalchemy`, `psycopg`, `pydantic`, `pytest`. The sanitizer uses only the stdlib (`math.isnan`, `math.isinf`). No new dependencies.
**Storage**: Postgres (production) + SQLite (test stratum). The fix touches both — `JSONType = JSONB().with_variant(JSON(), "sqlite")` is a single TypeDecorator chain.
**Testing**: pytest. Two new test files under `agent/tests/`:
  - `tests/unit/test_jsonb_sanitizer.py` — sanitizer contract (FR-001..FR-005, FR-008, SC-005).
  - `tests/integration/test_jsonb_nan_persistence.py` — boundary integration via `ToolCallRepo.create` (FR-011, SC-003).
**Target Platform**: Linux container (production), macOS host (dev). Identical behavior on both.
**Project Type**: agent component only (Constitution Principle VI). Zero edits to `etl/` or `frontend/`. Touches:

- `agent/src/discogs_agent/persistence/models.py` — replace the `JSONType` definition with a sanitizing `TypeDecorator` (or add the sanitizer as a `process_bind_param` hook on the existing column type).
- `agent/src/discogs_agent/persistence/sanitize.py` — NEW. The pure sanitizer function.
- `agent/tests/unit/test_jsonb_sanitizer.py` — NEW. Unit tests for the sanitizer.
- `agent/tests/integration/test_jsonb_nan_persistence.py` — NEW. End-to-end persistence integration test.
- `specs/004-agent-v1/contracts/postgres-schema.md` — amended (new §7).

**Performance Goals**: the sanitizer recurses through dicts that are typically tens of KB. Cost is microseconds per write. No batching, no async, no caching. Negligible compared to the ~5s LLM round-trip the typical run includes.

**Constraints**:
- The sanitizer MUST NOT mutate its input (FR-005). It returns a new value.
- The sanitizer MUST be applied at exactly one chokepoint (FR-007 + SC-006). Verifiable by grep.
- The fix MUST be backwards-compatible: existing rows in production Postgres are by definition already standards-compliant; the sanitizer only touches write paths. Existing tests with clean dicts pass unchanged.
- The fix MUST cover all five JSONB columns. Verifiable by hooking at the `JSONType` level (one site) rather than at each `Repo.create` call site (five sites).

**Scale/Scope**: ~30 LOC for the sanitizer + ~10 LOC for the TypeDecorator wiring. ~120 LOC across two test files. ~50 lines of new markdown in `004/contracts/postgres-schema.md`. No public API changes, no new endpoints, no schema changes (DDL unchanged — the `JSONB`/`JSON` column types are unchanged at the database level).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Engaged? | Verdict |
|-----------|----------|---------|
| I — Layered, Contract-First Data Architecture | No | No published-DuckDB schema change. The fix is in the agent's persistence layer; no impact on what the ETL produces. |
| II — Streaming, Bounded-Memory Processing | No | Pipeline-side principle; not engaged. |
| III — Reproducible Runs | No | Not directly engaged. The fix improves run *completeness* — runs that would have 500'd now succeed — but the manifest/log shape is unchanged. |
| IV — Data Quality Gates | No | DQ checks are pipeline-side. The bug is downstream of the published DuckDB; the published data is fine. |
| V — Agent-Friendly Analytics Surface | No | No new tables, no SQL changes, no schema-context changes. |
| VI — Two Components, One Contract | Yes | Fully inside `agent/`. Zero edits to `etl/` or `frontend/`. ✅ |
| VII.a — Configuration sources | No | No new env vars; the sanitizer is unconfigurable (and rightly so — RFC 8259 isn't operator-tunable). |
| VII.b — Prompt-authoring discipline | No | No prompt changes. |
| VII.c — Read-only runtime mechanics | **Yes — load-bearing analog** | This feature operationalizes the **write-side** counterpart to VII.c. The principle says "when a runtime constraint declares a resource read-only, the constraint's *consequences* MUST be documented alongside it." The symmetric statement: "when a write target declares a content-shape constraint (Postgres JSONB requires RFC-8259 JSON), the constraint's *consequences* (upstream code paths producing non-standard JSON) MUST be documented and mitigated alongside it." The 004 contract amendment + the sanitizer + the regression test are the named-incident mitigation. ✅ |

**Gate result**: PASS. Zero violations to record. The feature is a follow-through on the discipline VII.c established in 006.

**Component(s) touched**: `agent/` only.

## Project Structure

### Documentation (this feature)

```text
specs/010-jsonb-nan-sanitization/
├── spec.md                                          # Already written
├── plan.md                                          # This file
├── research.md                                      # Phase 0 — chokepoint + test + sanitizer design
├── contracts/
│   └── amendment-004-postgres-schema.md             # Verbatim §7 insertion text
├── checklists/
│   └── requirements.md                              # 16/16 PASS
├── quickstart.md                                    # Manual reproducer + regression-test invocation
└── tasks.md                                         # Phase 2 output
```

No `data-model.md`: this feature introduces no new entities. The five JSONB columns are already documented in `004/contracts/postgres-schema.md`.

### Source Code (repository root)

```text
agent/
├── src/discogs_agent/persistence/
│   ├── sanitize.py                                  # NEW — `sanitize_for_jsonb(value)` pure function
│   └── models.py                                    # MODIFIED — JSONType wraps a sanitizing TypeDecorator
└── tests/
    ├── unit/
    │   └── test_jsonb_sanitizer.py                  # NEW — sanitizer contract tests (6 cases)
    └── integration/
        └── test_jsonb_nan_persistence.py            # NEW — end-to-end persistence test through ToolCallRepo
```

`specs/004-agent-v1/contracts/postgres-schema.md` is amended in the same change set.

**Structure Decision**: agent-only patch + 004-contract amendment. Same shape as 007 (amends `004/contracts/code-generation.md`) and 009 (amends `005/contracts/schema-context.md`). The constitution is **not** amended.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

(Not applicable — no constitution violations.)

## Phase 0 — Research

Three focused decisions. Full long-form in [`research.md`](./research.md); recap below for the Constitution Check trail.

1. **Chokepoint placement: SQLAlchemy `TypeDecorator` wrapping `JSONType`**. The `TypeDecorator.process_bind_param` hook runs on every column-write at the SQLAlchemy → driver boundary. One site, covers all five JSONB columns, covers both Postgres and SQLite, doesn't disturb read paths. Alternative chokepoints (per-Repo `create()` calls; SQLAlchemy `before_insert`/`before_update` event hooks) considered and rejected — see research §R1.

2. **Test strategy: two layers, both deterministic**. Layer A (unit): `test_jsonb_sanitizer.py` exercises the pure function with 6 cases (top-level NaN, nested NaN, NaN in list, Infinity, idempotence, mutation-freedom). Layer B (integration): `test_jsonb_nan_persistence.py` constructs a `ToolCall` row with `output_json={"preview": [{"country": float('nan'), ...}]}`, calls `repo.create(...)` against the SQLite test stratum, asserts the row reads back with `None`. The user-facing failure is Postgres-only (SQLite silently swallows NaN before the fix), but the SQLite test confirms the sanitizer fired (because read-back returns `None`, not a NaN-like sentinel). A Postgres-fixture variant is documented as a stretch — not gated.

3. **Sanitizer signature: `sanitize_for_jsonb(value: Any) -> Any`**. Returns a new value. Recursion handles `dict`, `list`, `tuple` (converted to list). For numeric values, `math.isnan` and `math.isinf` are the only inspection — no string-matching, no JSON serialization round-trip. Idempotent on already-clean inputs. ~25 LOC.

**Output**: [`research.md`](./research.md) with the long-form decisions and alternatives.

## Phase 1 — Design & Contracts

**Prerequisites**: `research.md` complete (decisions 1–3 above resolved).

1. **Entities** — none. Skip `data-model.md`.

2. **Contracts** → one document:

   **[`amendment-004-postgres-schema.md`](./contracts/amendment-004-postgres-schema.md)** — exact prose for a new §7 in `004/contracts/postgres-schema.md`. Inserted between the existing §6 ("Backward-compat & seeds") and the document's end. Documents:
   - The JSONB input invariant ("every dict written to a JSONB column MUST be RFC-8259-compliant — no NaN, no Infinity, no -Infinity").
   - The sanitizer's contract (signature, idempotence, mutation-freedom, recursion through dicts/lists/tuples).
   - The chokepoint location (`TypeDecorator` wrapping `JSONType` in `models.py`).
   - The named incident (run `4b0f6979-71f8-41dc-8d79-204933621f3a`).
   - The disciplinary analog (Constitution VII.c, write-side counterpart).
   - Backwards-compat note: `JSONType` API unchanged; existing rows unaffected.

   No standalone API or schema contract is created; the agent's HTTP API and the Postgres DDL are unchanged. The amendment is the only contract change.

3. **Quickstart** → [`quickstart.md`](./quickstart.md). Walks through:
   - The manual reproducer (top countries question against the live agent) — confirms post-fix the run completes 200.
   - The regression-test invocation (`pytest agent/tests/unit/test_jsonb_sanitizer.py agent/tests/integration/test_jsonb_nan_persistence.py`).
   - Inspecting a tool-call row's `output_json` to confirm NULL cells render as JSON `null`.
   - The revert-and-rerun sanity check that proves the regression catches a regression.

4. **Agent context update** → ✅ Already done: `CLAUDE.md` SPECKIT block updated to point at this plan immediately after spec was written.

**Output of Phase 1**: `contracts/amendment-004-postgres-schema.md`, `quickstart.md`. CLAUDE.md already updated.

## Re-check Constitution Check after Phase 1 design

Phase 1 produces no new entities, no new APIs, no new env vars, no new dependencies, no new prompt files, no schema changes. The only artifact crossing 010's boundary is the amendment to `004/contracts/postgres-schema.md` — governed by Constitution VI (single contract surface) and VII.c (the disciplinary analog). The amendment satisfies VII.c by documenting the constraint's consequences alongside the constraint.

**Gate result (post-design)**: PASS. No new violations introduced.
