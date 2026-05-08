# Feature Specification: JSONB NaN sanitization

**Feature Branch**: `010-jsonb-nan-sanitization`
**Created**: 2026-05-08
**Status**: Draft
**Input**: A user-reported bug. Running an agent query that produced a dataframe containing NULL values (likely a country-aggregation question with rows where `country IS NULL`) caused the agent to 500 with `psycopg.errors.InvalidTextRepresentation: invalid input syntax for type json: Token "NaN" is invalid`. The dataframe-preview rows contained `{"country": NaN, "number_of_releases": 649673}`. Postgres JSONB rejects non-standard JSON; Python's `json.dumps` is `allow_nan=True` by default. Stack trace shows the failure path: `sandbox_executor → _persist_tool_call → ToolCallRepo.create → SQLAlchemy → psycopg → Postgres`. Run `4b0f6979-71f8-41dc-8d79-204933621f3a`.

## Overview

This is a silent-class-of-failure bug: any agent run that produces a dataframe with NULL cells in the preview rows fails persistence with a 500. The same query class works fine when no preview row contains a NULL. The "Top countries" curated demo question (`008/contracts/curated-questions.md` Q4) is a likely repro because Discogs releases legitimately have NULL country.

The bug surfaces at the persistence-write boundary. Five JSONB-shaped columns exist (`agent_runs.metadata_json`, `agent_threads.metadata_json`, `agent_tool_calls.input_json`, `agent_tool_calls.output_json`, `agent_artifacts.metadata_json`). Any data flowing into them must be RFC-8259-compliant JSON: no `NaN`, no `Infinity`, no `-Infinity`. None of these tokens is legal JSON. Postgres enforces; psycopg's default JSON encoder happily emits them; Pydantic preserves them on `model_dump()`; pandas dataframes routinely produce `float('nan')` for NULL cells.

The fix lands at the persistence boundary — sanitize all dicts before insertion, replacing NaN/Infinity floats with Python `None`. This covers all five JSONB columns through one chokepoint, and it's robust against the next code path that legitimately produces a NaN (some other tool, a future LLM-generated calculation, a join through a sparse view, etc.).

The fix is small (~20-30 LOC + a regression test) but it changes a contract — `004/contracts/postgres-schema.md` gets a new §7 declaring the JSONB input invariant. Constitution VII.c (read-only runtime mechanics) is the closest discipline analog; this feature operationalizes it for the persistence-write boundary the way 009 operationalized VII.b for the schema-context block.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Queries with NULL-containing dataframes complete successfully (Priority: P1)

A user submits any agent query whose dataframe preview contains rows with NULL cells (a country-aggregation question, a label-aggregation question, or any question where the underlying data legitimately has missing values). The agent run completes with HTTP 200 + a populated chart artifact + a `dataframe_preview` whose NULL cells are JSON-valid (`null`, not `NaN`).

**Why this priority**: Any nondeterministic 500 is a P0 correctness bug. The reproducer is one of the seven curated demo questions. Demo Day cannot be confidently scheduled with this bug present.

**Independent Test**: Submit "What are the top 15 countries by number of releases?" against the live agent post-fix. Verify the response is HTTP 200 with `status: "succeeded"` and that the `dataframe_preview` field is well-formed JSON (parseable by `json.loads`, no `NaN` tokens, NULLs surface as JSON `null`).

**Acceptance Scenarios**:

1. **Given** the agent stack is running with a published catalog containing NULL `country` values, **When** the user submits "What are the top 15 countries by number of releases?", **Then** the response is HTTP 200, contains a chart artifact, and the `dataframe_preview` field is valid JSON parseable by any RFC-8259 parser.
2. **Given** the same setup, **When** the user inspects the `agent_tool_calls.output_json` row for the run via the inspection API (`GET /runs/{id}`), **Then** the JSON is well-formed and any NULL dataframe cells appear as JSON `null` (not `NaN` and not the string `"NaN"`).
3. **Given** the same setup, **When** the user submits any other query whose dataframe legitimately contains NULL cells (e.g., labels with NULL country, releases with NULL year), **Then** the run completes without a 500 from the persistence layer.

---

### User Story 2 — Other JSONB-bound writes are equally protected (Priority: P2)

A future agent change writes a different dict shape into one of the JSONB columns — `agent_runs.metadata_json`, `agent_threads.metadata_json`, or `agent_artifacts.metadata_json`. If that dict ever contains a NaN or Infinity float (e.g., a malformed cost calculation, a stats summary with division by zero), the persistence layer normalizes it without raising.

**Why this priority**: P1 closes the specific reported failure. P2 verifies that the fix is general — the boundary discipline applies to every JSONB column, not just `agent_tool_calls.output_json`. This story locks in the breadth.

**Independent Test**: A unit test that constructs a dict with `NaN`/`Infinity`/`-Infinity` at top-level, in nested dicts, and inside lists, then asserts that the sanitizer produces a JSON-valid version.

**Acceptance Scenarios**:

1. **Given** a dict containing top-level NaN, **When** sanitized, **Then** the NaN is replaced with `None`.
2. **Given** a dict containing nested dicts and lists with NaN/Infinity values, **When** sanitized, **Then** every NaN/Infinity is replaced with `None` regardless of nesting depth.
3. **Given** a normal dict with no NaN/Infinity, **When** sanitized, **Then** the output equals the input (idempotent on already-clean data).

---

### User Story 3 — A regression test prevents this class of bug from coming back (Priority: P1)

A future contributor adds a new persistence path or modifies an existing one. The regression test catches any drift that re-opens the silent NaN-in-JSONB failure.

**Why this priority**: 006/009 added regression tests as gates for their respective bug classes. Without one here, the next "I'll persist this dict" PR could re-introduce the failure.

**Independent Test**: Run the regression test. It must pass on the post-fix codebase and (verified during implementation) fail on the pre-fix codebase.

**Acceptance Scenarios**:

1. **Given** the post-fix codebase, **When** the regression test runs, **Then** it asserts that (a) the sanitizer correctly handles NaN/Infinity at every nesting level, (b) calling `_persist_tool_call` with an output containing NaN succeeds against a Postgres-shaped session, (c) the persisted JSON roundtrips back to a dict with `None` (not `NaN`).
2. **Given** a hypothetical revert of the fix, **When** the regression test runs, **Then** it fails (verified manually during implementation).

---

### Edge Cases

- **Already-clean dict**: sanitizer is idempotent — a dict with no NaN/Infinity passes through unchanged.
- **Pandas-shaped output**: dataframes are converted to dicts via `to_dict(orient="records")` in the generated code. The sanitizer runs on the resulting dict, NOT on the dataframe — by the time data reaches the persistence boundary it's already a plain Python dict.
- **Nested structures**: NaN can appear inside lists inside dicts inside lists. The sanitizer recurses.
- **Non-NaN floats that ARE valid JSON**: regular floats (0.0, 1.5, -3.14) are preserved exactly.
- **Pydantic models**: `model_dump()` happily preserves NaN floats. The sanitizer runs after `model_dump()`, before SQLAlchemy `flush()`.
- **SQLite test stratum**: the SQLite `JSON` type behaves differently from Postgres `JSONB`. SQLite would silently accept `NaN` (because Python's default JSON encoder writes it). The sanitizer fixes both — production correctness AND test fidelity.
- **Performance**: the sanitizer recurses through dicts that are typically tens of KB. Cost is negligible compared to LLM round-trip time. No batching or async needed.

## Requirements *(mandatory)*

### Functional Requirements

**Sanitizer**

- **FR-001**: A pure function MUST exist that takes any JSON-serializable Python value (dict, list, primitives) and returns a structurally identical value with all `float('nan')`, `float('inf')`, and `float('-inf')` replaced with `None`.
- **FR-002**: The sanitizer MUST recurse through arbitrarily-nested dicts and lists.
- **FR-003**: The sanitizer MUST be idempotent — applying it twice MUST produce the same result as applying it once. (This is automatic if applied to already-clean data; the contract makes it explicit.)
- **FR-004**: The sanitizer MUST preserve all valid JSON values exactly: regular floats, ints, strings, bools, None, dicts, lists, and tuples (tuples MAY be converted to lists, but their contents MUST be preserved).
- **FR-005**: The sanitizer MUST NOT mutate its input — it returns a new value.

**Persistence boundary**

- **FR-006**: The sanitizer MUST be applied to every dict written into a JSONB column before SQLAlchemy `flush()`. The five JSONB columns (per `004/contracts/postgres-schema.md` §1) are: `agent_runs.metadata_json`, `agent_threads.metadata_json`, `agent_tool_calls.input_json`, `agent_tool_calls.output_json`, `agent_artifacts.metadata_json`.
- **FR-007**: The sanitization point MUST be a single chokepoint — either inside the SQLAlchemy event hook for the `JSONType` column, or inside each `Repo.create` method, or via a custom SQLAlchemy `TypeDecorator` wrapping `JSONType`. The implementation choice is deferred to the plan; the FR pins that "every JSONB write is sanitized" without per-call-site discipline.
- **FR-008**: After sanitization, the dict MUST be valid JSON serializable by Python's stdlib `json.dumps` with `allow_nan=False`. (This is the wire-level contract Postgres enforces.)

**Contract**

- **FR-009**: `specs/004-agent-v1/contracts/postgres-schema.md` MUST be amended to declare the JSONB input invariant (no NaN/Infinity), document the sanitizer's contract, and name the chokepoint.

**Regression coverage**

- **FR-010**: A unit test MUST exist that covers the sanitizer's contract: top-level NaN, nested NaN, NaN inside lists, NaN-Infinity-and-clean roundtrips, idempotence, mutation-freedom.
- **FR-011**: An integration test MUST exist that exercises the persistence boundary: build a dict with NaN values, write it through the chosen chokepoint (e.g., `ToolCallRepo.create(..., output_json=...)` with NaN inside `output_json`), `flush()`, and assert the row reads back with `None` not `NaN`. The test MUST run against the SQLite test stratum at minimum; if the test infrastructure supports a Postgres fixture (the user-facing failure mode), the test SHOULD assert against Postgres too.

### Key Entities *(include if feature involves data)*

This feature does not introduce new entities. It strengthens the contract for an existing data type (`JSONType` per `models.py:65` — `JSONB` on Postgres, `JSON` on SQLite). The relevant entities are the five JSONB columns enumerated in FR-006 — facts already documented in `004/contracts/postgres-schema.md` §1, not new design.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The user's reported reproducer (top countries question, run `4b0f6979-71f8-41dc-8d79-204933621f3a` family) succeeds end-to-end against the live agent post-fix on at least 9 of 10 attempts. Failure budget reflects LLM cheap-model variance, not the persistence fix (which is deterministic).
- **SC-002**: 0 of 10 attempts at the reproducer trigger an `InvalidTextRepresentation` Postgres error in the agent logs.
- **SC-003**: A new regression test (`agent/tests/integration/test_jsonb_nan_sanitization.py` or similar — final filename pinned in tasks.md) passes on the post-fix codebase and is verified to fail when the sanitizer is removed (manual sanity check during implementation).
- **SC-004**: The full agent test suite (`pytest tests/`) remains green post-fix. No existing tests regress on the sanitization change.
- **SC-005**: A unit test for the sanitizer covers all 6 cases from FR-010 (top-level NaN, nested NaN, NaN-in-list, Infinity, idempotence, mutation-freedom). Each case is a separately named test for traceability.
- **SC-006**: The sanitizer is applied at exactly one chokepoint. Verifiable by code review and by a grep that finds the import of the sanitizer at exactly one location in `agent/src/discogs_agent/persistence/` (or wherever the chokepoint lands per the plan's decision).

## Assumptions

- **Scope is the persistence-write boundary, not the upstream data path.** Sandboxes, generated code, and Pydantic models continue to produce dicts that may contain NaN. The fix declares that "any data flowing into JSONB MUST be sanitized at the boundary" — the boundary is the only place where standards-compliance is enforced. Upstream code remains free to use NaN as a missing-data sentinel.
- **No constitution amendment.** Constitution VII.c (read-only runtime mechanics) was already amended in 006 to declare that "when a runtime constraint declares a resource read-only, the constraint's *consequences* MUST be documented alongside it." This bug is the same shape applied to a write-side constraint: Postgres JSONB declares "RFC-8259-compliant JSON only," and that constraint's consequences (NaN floats from upstream code paths) must be documented and mitigated. The 004/contracts/postgres-schema.md amendment is the load-bearing artifact; no constitution change needed.
- **Sanitizer placement: SQLAlchemy `TypeDecorator` is the natural choice.** The plan will validate this. A `TypeDecorator` wrapping `JSONType` runs on every column-write across all five JSONB columns and across both Postgres and SQLite — single chokepoint, FR-007 satisfied. Alternative chokepoints (per-Repo, per-event-hook) are evaluated in research.
- **Tuples → lists is acceptable.** Pydantic `model_dump()` typically returns plain dicts/lists; tuples are rare in this code path. If a tuple does appear, the sanitizer converts it to a list (which JSON would do anyway). Documented in FR-004.
- **`-0.0`, `+0.0`, very-large-finite floats**: not affected. The sanitizer touches only `nan`, `+inf`, `-inf` (`math.isnan` / `math.isinf`).
- **Backwards compatibility**: all existing rows in production Postgres that successfully serialized are by definition already standards-compliant. The sanitizer doesn't touch read paths. Existing tests that use clean dicts pass unchanged.
- **Out of scope**: retroactive cleanup of any partially-corrupted persistence rows (none exist — the bug *prevented* writes rather than producing bad rows). Out of scope: stricter Pydantic-side validation (could be added later if false-NaN-from-upstream becomes a recurring pattern). Out of scope: tightening the generated-code prompt to avoid producing NaN — Constitution VII.b restricts what we can put in prompts; the fix lives at the persistence boundary instead.

## Dependencies

- **Existing `004/contracts/postgres-schema.md`** — this feature amends it. Same shape as 007's amendment to `004/contracts/code-generation.md` and 009's amendment to `005/contracts/schema-context.md`.
- **Existing `agent/src/discogs_agent/persistence/models.py`** — `JSONType = JSONB().with_variant(JSON(), "sqlite")` is the type the sanitizer wraps (or hooks).
- **Existing `agent/src/discogs_agent/persistence/repositories.py`** — where the chokepoint MAY live (alternative: a `TypeDecorator` in `models.py`).
- **Constitution VII.c (read-only runtime mechanics)** — the closest disciplinary analog. The feature operationalizes the analogous "write-side" version: declare the constraint (RFC 8259) and document its consequences (NaN from upstream).
- **001 + 003 published-DuckDB contracts** — source of truth for what data shapes can flow into the agent. Their NULL-tolerance is what produces the NaN floats. Unchanged.
- **No dependency on the 008-agent-frontend-v1 work** — the frontend would surface the bug to the user (HTTP 500 banner), but the fix is agent-side. 010 lands independently of 008.
- **No dependency on the 009-schema-context-join-graph work** — orthogonal fix surface (rendering vs. persistence).
