# Tasks: Agent Schema Context Enrichment

**Input**: Design documents from `/specs/005-agent-schema-context/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: REQUIRED for this feature. The spec mandates a regression suite (FR-008, SC-001/-002/-004/-005), so test tasks are part of every user story phase.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- File paths are absolute against repo root.

## Path Conventions

This is a **single-component** change inside `agent/`:

- Source: `agent/src/discogs_agent/`
- Tests: `agent/tests/{unit,integration,golden}/`
- Migrations: `agent/src/discogs_agent/persistence/migrations/versions/`
- Prompts: `agent/src/discogs_agent/prompts/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the working environment. No source-code changes here; this phase exists so the implementer can verify they're starting from a green baseline.

- [X] T001 Verify the agent venv builds and the existing test suite is green: from `agent/`, run `./.venv/bin/python -m pytest tests/unit -q` and confirm all 45 tests pass before any edits.
- [X] T002 Verify the published DuckDB at `data/published/duckdb/discogs.duckdb` is the April 2026 full-dump (sanity-check by reading `release_unique_view.run_id` and confirming `style='Techno'` returns >100k rows on `release_fact`). Skip with a recorded warning if running against a sample DB.
- [X] T003 Confirm Docker Compose stack (`agent-api-1`) starts cleanly, the alembic migration applies, and `/health` returns `{"status":"ok"}` per `agent/README.md`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema-context enrichment + Postgres migration. EVERY user story depends on at least one item in this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 Extend the `SchemaContext` TypedDict in `agent/src/discogs_agent/duckdb_layer/schema.py` with the new fields per `contracts/schema-context.md`: `sample_values: dict[str, dict[str, list[SampleValue]]]`, `domain_glossary: list[str]`, `published_run_id: str | None`, `rendered_block: str`, `rendered_token_count: int`. Define a nested `SampleValue` TypedDict with `value` and `count`.
- [X] T005 In `agent/src/discogs_agent/duckdb_layer/schema.py`, add a private `_collect_sample_values(con) -> dict[str, dict[str, list[SampleValue]]]` that issues bounded `SELECT col, COUNT(*) c FROM tbl WHERE col IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT N` queries for: `release_unique_view.primary_genre` (no LIMIT — only 14 distinct), `release_unique_view.primary_format_group` (no LIMIT), `release_unique_view.decade` (no LIMIT), `release_unique_view.country` (LIMIT 20), `release_fact.style` (LIMIT 50). Returns the keyed dict from `data-model.md §1`.
- [X] T006 In `agent/src/discogs_agent/duckdb_layer/schema.py`, add a private `_build_domain_glossary() -> list[str]` returning the three exact strings from `data-model.md §1.domain_glossary`. Pure data; no DuckDB call.
- [X] T007 In `agent/src/discogs_agent/duckdb_layer/schema.py`, add a public `render_schema_block(ctx: SchemaContext) -> str` that emits the plain-text rendering specified in `contracts/schema-context.md` (Available tables → Sample distinct values → Domain glossary). This becomes the single source of truth for the `{schema_context_block}` placeholder used by all prompts.
- [X] T008 In `agent/src/discogs_agent/duckdb_layer/schema.py`, add a private `_count_tokens(text: str, model: str) -> int` using `tiktoken.encoding_for_model()` with a graceful fallback (`encoding_for_model` may raise on a model alias; fall back to `get_encoding("cl100k_base")`).
- [X] T009 In `agent/src/discogs_agent/duckdb_layer/schema.py`, add a private `_truncate_to_budget(samples, glossary, model, budget=600) -> tuple[samples, str, int]` that renders, counts tokens, and progressively drops the lowest-frequency samples per the order in `research.md §R-3` (country 20→10, then style 50→30) until the rendered block fits. Emits a structured `obslog` warning `schema_context_truncated_for_token_budget` on every truncation.
- [X] T010 Modify `read_schema_context()` in `agent/src/discogs_agent/duckdb_layer/schema.py` to call `_collect_sample_values()`, `_build_domain_glossary()`, capture `published_run_id` via `SELECT MAX(run_id) FROM release_unique_view` (handle absence gracefully), apply `_truncate_to_budget()`, populate `rendered_block` + `rendered_token_count`, and return the extended `SchemaContext`. Cache semantics (`_cache`, `reset_schema_cache()`) stay unchanged.
- [X] T011 [P] Create the Alembic migration `agent/src/discogs_agent/persistence/migrations/versions/005_add_succeeded_empty.py` per `contracts/empty-result.md`. `upgrade()`: drop the existing `agent_runs_status_check`, recreate it with `succeeded_empty` added. `downgrade()`: reverse. Ensure the revision `down_revision` points to whatever the current head is at the time of authoring (run `./.venv/bin/python -m alembic -c src/discogs_agent/persistence/alembic.ini heads` first).
- [X] T012 [P] Update the SQLAlchemy `CheckConstraint` for `agent_runs.status` in `agent/src/discogs_agent/persistence/models.py` (around line 166 per `004-agent-v1/contracts/postgres-schema.md`) to include `succeeded_empty`. The runtime constraint enforced by Postgres comes from the migration; the model constraint is for ORM-level diagnostics.
- [X] T013 Run the new migration locally — from `agent/`, `./.venv/bin/python -m alembic -c src/discogs_agent/persistence/alembic.ini upgrade head`. Confirm the constraint update with `psql ... -c "\d agent_runs"`.

**Checkpoint**: schema context now ships sample values + glossary + rendered block under 600 tokens; Postgres accepts `succeeded_empty`. User-story work can begin in parallel.

---

## Phase 3: User Story 1 — Style queries return non-empty results (Priority: P1) 🎯 MVP

**Goal**: Style-keyed questions (Techno, House, Drum n Bass, ...) return SQL that filters by `style` on `release_fact`, so the resulting chart contains real data.

**Independent Test**: Run the 10-canonical-style golden suite; assert `row_count > 0` and `dataframe_preview` non-empty for each.

### Implementation for User Story 1

- [X] T014 [P] [US1] Replace the per-file duplicate `_summarize_schema()` helpers with a single import. Remove the helper from `agent/src/discogs_agent/graph/nodes/code_generator.py` (lines ~21-29) and have `_render_prompt` use `schema_context["rendered_block"]` directly.
- [X] T015 [P] [US1] Same treatment in `agent/src/discogs_agent/graph/nodes/query_understanding.py` — drop the local `_summarize_schema`, use `schema_context["rendered_block"]`.
- [X] T016 [P] [US1] Same treatment in `agent/src/discogs_agent/tools/query_classifier.py` — drop the local `_summarize_schema`, use `schema_context["rendered_block"]`.
- [X] T017 [US1] Edit `agent/src/discogs_agent/prompts/router.md`: replace the `{tables_summary}` + `{has_master_fact}` block with a single `{schema_context_block}` placeholder. Keep all other prompt structure intact.
- [X] T018 [US1] Edit `agent/src/discogs_agent/prompts/query_understanding.md`: same treatment as T017.
- [X] T019 [US1] Edit `agent/src/discogs_agent/prompts/code_generator.md`: same treatment, AND keep the existing `Critical rule for release_fact` line — it complements (does not duplicate) the new glossary.
- [X] T020 [US1] Edit `agent/src/discogs_agent/prompts/repair_code.md`: same treatment.
- [X] T021 [US1] Update each render-call site (T014/T015/T016) to substitute `{schema_context_block}` from `ctx["rendered_block"]` instead of `tables_summary`/`has_master_fact`. Confirm `code_generator.py` does this for both `retry_count == 0` and the repair-prompt branch (lines ~57 and ~69 today).

### Tests for User Story 1

- [X] T022 [P] [US1] Create `agent/tests/golden/test_canonical_styles.py`. Drives the full graph (with the LLM-stub backend, `LLM_BACKEND=stub`) for 10 styles: Techno, House, Ambient, Drum n Bass, Trance, Dub, Garage, Disco, Acid Jazz, Funk. Asserts `row_count > 0`, `dataframe_preview` non-empty, and the SQL string contains `style = '<value>'` (NOT `primary_genre`) for each.
- [X] T023 [P] [US1] In the LLM stub (`agent/src/discogs_agent/llm/stub.py`), add a stub-response branch that, when the prompt contains the new glossary AND a "Techno"-class style word, emits SQL using `style = '<word>'` on `release_fact`. This is the deterministic substitute for live OpenAI calls in the golden test. Document this branch with a one-line comment pointing to the test file.
- [X] T024 [P] [US1] Extend `agent/tests/unit/test_query_classifier.py` — under the enriched schema context, the existing 4 cases continue to pass AND a new case: a question about "Techno" routes to `simple` (or `complex`), NOT to `unsupported`. The fixture must populate the new `rendered_block` field.

**Checkpoint**: 10/10 canonical style queries return non-empty data. SC-001 verified. The chart for "Show the evolution of Techno releases over time" now renders real data.

---

## Phase 4: User Story 2 — Trend questions prefer `decade` (Priority: P2)

**Goal**: For evolution/over-time/trend questions without explicit yearly granularity, the agent groups by `decade`. Yearly intent (literal "year"/"yearly"/"annual") still routes to `year`.

**Independent Test**: Submit a 20-question evaluation set; assert ≥ 90% of generated SQL groups by `decade`. Hard pass: 18/20.

### Implementation for User Story 2

- [X] T025 [US2] No new code path needed — the decade-preference rule is already in the `domain_glossary` from T006 and rendered into every prompt via the block from T007. Verify this by reading `prompts/code_generator.md` after T019 and confirming the rendered block (in a dry run) includes the decade hint.
- [X] T026 [US2] In the LLM stub (`agent/src/discogs_agent/llm/stub.py`), update the SQL-generation branch so that when the prompt contains the decade-preference hint AND the user query contains "evolution"/"over time"/"trend"/"history" (case-insensitive) but NOT "year"/"yearly"/"annual", the stub emits SQL grouped by `decade`. Otherwise group by `year`.

### Tests for User Story 2

- [X] T027 [P] [US2] Create `agent/tests/golden/test_decade_preference.py` with 20 question/expected-grain pairs (15 trend questions → expect `decade`; 5 yearly-intent questions → expect `year`). Run through the graph (stub backend), assert ≥18/20 match the expected grain. Also assert all 20 return `row_count > 0` (regression on US1 too).

**Checkpoint**: SC-005 verified — trend questions prefer `decade`.

---

## Phase 5: User Story 3 — Empty results surface as `succeeded_empty` (Priority: P2)

**Goal**: Zero-row outcomes produce a distinct terminal state with a "no matching releases" message and the SQL preserved, instead of a blank chart with `status: succeeded`.

**Independent Test**: Submit a query for a hallucinated style (e.g., "Polka"). Assert response has `status: "succeeded_empty"`, `row_count: 0`, `dataframe_preview: []`, and `response` text contains "no matching releases".

### Implementation for User Story 3

- [X] T028 [P] [US3] Extend `agent/src/discogs_agent/tools/chart_validator.py`: add `"empty_result"` to the set of valid `reason` values. When the sandbox's `RESULT["row_count"] == 0` AND the chart artifact exists structurally, return `ValidatorOutput(valid=True, reason="empty_result", chart_path=..., row_count=0)` per `contracts/empty-result.md`.
- [X] T029 [US3] Extend `agent/src/discogs_agent/graph/nodes/chart_validator.py`: in `chart_validator_node`, if `result.valid and result.reason == "empty_result"`, set `state["terminal_status"] = "succeeded_empty"` and `state["validation_result"] = result.model_dump()`; do NOT request retry. The existing `should_retry` logic must NOT fire for this branch.
- [X] T030 [US3] Extend `validation_edge` in the same file so that a `terminal_status == "succeeded_empty"` always routes to `response_synthesizer`, never back to `code_generator`.
- [X] T031 [US3] Extend `agent/src/discogs_agent/graph/nodes/response_synthesizer.py`: in the status-derivation block (around line 35-56), recognise `terminal_status == "succeeded_empty"` and pass it through. Update `_build_result_block` so the empty-result body includes the SQL, the literal "no matching releases" line, and the diagnostic hint per `contracts/empty-result.md`. Do NOT include `Chart artifact:` in the result block when the status is `succeeded_empty`.
- [X] T032 [US3] Edit `agent/src/discogs_agent/prompts/response_synthesizer.md`: add a short section *"If status is succeeded_empty, write a single short paragraph that (a) says no releases match the query, (b) shows the SQL that ran, and (c) suggests the user check whether they meant a `style` or a `primary_genre`. Do NOT mention a chart."*
- [X] T033 [US3] Extend `agent/src/discogs_agent/api_query.py`: where the API maps `final_state` → `QueryResponse`, ensure `chart_artifact` is set to `None` and `dataframe_preview` to `[]` when `status == "succeeded_empty"`. Also confirm the `status: str` field already accepts the new value (no Literal pin in the model).

### Tests for User Story 3

- [X] T034 [P] [US3] Extend `agent/tests/unit/test_chart_validator.py` (or create if absent — check first): a test fixture where the sandbox returns `RESULT={"row_count": 0, "chart_path": "...", ...}`. Assert `valid=True`, `reason="empty_result"`, and the node sets `terminal_status="succeeded_empty"` with no retry.
- [X] T035 [P] [US3] Add a test in `agent/tests/unit/` for `validation_edge`: given `terminal_status="succeeded_empty"`, the next node must be `response_synthesizer` regardless of `should_retry`.
- [X] T036 [P] [US3] Add a golden test `agent/tests/golden/test_empty_result.py`: submit a query for "Polka releases over time" through the graph (stub backend, with the stub returning SQL that filters `style = 'Polka'`). Assert API response has `status="succeeded_empty"`, `row_count=0`, `chart_artifact is None`, `dataframe_preview=[]`, and `"no matching releases"` appears in `response`.

**Checkpoint**: SC-002 verified — no blank-chart-with-status-succeeded responses remain in the regression suite.

---

## Phase 6: User Story 4 — Schema sample values surfaced (Priority: P3)

**Goal**: The structural fix that makes US1 self-correcting — confirm the enriched schema context is observable, bounded, and present in every prompt-rendering call site.

**Independent Test**: Inspect the cached `SchemaContext`; assert `sample_values` contains the four required column blocks and `rendered_token_count <= 600`.

### Tests for User Story 4

- [X] T037 [P] [US4] Create `agent/tests/unit/test_schema_context.py` (or extend the existing one — find with `find agent/tests -name "*schema*"`): assert the extended `SchemaContext` shape per `contracts/schema-context.md`: `sample_values` keys present, `domain_glossary` is a list of the three required strings, `published_run_id` populated when the column exists, `rendered_token_count <= 600`, and `rendered_block` is a non-empty string containing the literal "primary_genre" and "style" tokens.
- [X] T038 [P] [US4] Create `agent/tests/integration/test_schema_context_real_duckdb.py`. Connect to a fixture DuckDB (reuse the small fixture from `004-agent-v1` if present; otherwise create a 50-release in-memory DuckDB with both `release_fact` and `release_unique_view` populated). Assert real sample values render — the rendered block must contain at least one style and at least one primary_genre value from the fixture data.
- [X] T039 [P] [US4] Add a test in `agent/tests/unit/test_schema_context.py` for the truncation path: monkey-patch the budget to 50 tokens, assert truncation happens, the warning fires, and the block still renders something.

**Checkpoint**: SC-003 + SC-004 verified — schema-context shape is bounded and tested.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end verification, docs, and final regression sweep.

- [X] T040 [P] Update `agent/README.md` with a short "Schema context enrichment" subsection pointing at `specs/005-agent-schema-context/quickstart.md` and explaining the new `succeeded_empty` status. One paragraph.
- [X] T041 [P] Run the full agent test suite (`unit`, `integration`, `golden`) from `agent/`: `./.venv/bin/python -m pytest tests -q`. Confirm 45 pre-existing + 10+ new tests all pass. Address any unexpected regressions before declaring done.
- [X] T042 [P] Run a static check that no new ETL imports leak in: `./.venv/bin/python -m pytest tests/unit/test_no_etl_imports.py -v` (this is the existing constitution-enforcement test from `004-agent-v1`).
- [X] T043 Run the live smoke from `quickstart.md` §4 against Docker Compose (rebuild `agent-api`, hit `/query` with the Techno question). Capture the response in a comment on the PR / branch checkpoint to demonstrate SC-001.
- [X] T044 Run the live smoke for the empty-result path (`Show Polka releases over time`); assert `status: succeeded_empty`. Capture the response.
- [X] T045 Update `CLAUDE.md` SPECKIT block with the final list of plan/spec/contracts paths if anything moved during implementation. (No-op if nothing moved.)
- [ ] T046 Final commit on the `005-agent-schema-context` branch with the implementation; do NOT merge until quickstart.md and SC-001/-002/-005 have been demonstrated locally.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all user stories.**
- **US1 (Phase 3)**: Depends on Foundational. Independent of US2/US3/US4.
- **US2 (Phase 4)**: Depends on Foundational. Slightly uses US1's prompt edits (T017–T020) for verification, but the core behavior is in foundational T006/T007 (the glossary already contains the decade rule).
- **US3 (Phase 5)**: Depends on Foundational (specifically T011 — the migration). Independent of US1/US2.
- **US4 (Phase 6)**: All tests; depends on Foundational. Touches no source code, only assertions.
- **Polish (Phase 7)**: Depends on all desired user stories.

### Within-phase dependencies

- T004 → T005, T006, T007, T010 (need the TypedDict before the helpers populate it).
- T005 + T006 → T010 (the builder uses both).
- T007 + T009 → T010 (the renderer + truncator are inputs to read_schema_context).
- T011 → T013 (write the migration before running it).
- T014–T020 are mostly independent files but T021 ties them together.
- T022 / T023 / T024 are the test set for US1; T023 (stub change) must precede T022 (golden test that exercises the stub).
- T028 → T029 → T030 → T031 → T033 (the empty-result chain is sequential through the graph).
- T032 (prompt edit) is independent of T028–T031 and can be done in parallel.
- T034 / T035 / T036 depend on T028–T033 being complete.

### Parallel Opportunities

- T011 + T012 (migration file + ORM model edit) — different files, run together with the schema.py work in T004–T010.
- T014 + T015 + T016 — three separate files, no overlap.
- T017 + T018 + T019 + T020 — four separate prompt files.
- T022 + T023 + T024 — three separate test files (T023 must land before T022 *runs*, but can be authored in parallel).
- T028 + T032 — different files (tool vs. prompt).
- T034 + T035 + T036 — three separate test files.
- T037 + T038 + T039 — three separate test files.
- T040 + T041 + T042 — independent polish tasks.

### Critical Path

`T001 → T004 → T005 → T010 → T013 → T021 → T022 → T029 → T036 → T041 → T046`

This is the longest dependency chain; everything else can run in parallel branches off of it.

---

## Parallel Example: Foundational Phase

```bash
# After T001-T003 (setup green), run the schema.py edit chain in foreground:
T004 → T005 → T006 → T007 → T008 → T009 → T010

# In parallel, the migration work:
T011 + T012 → T013
```

## Parallel Example: User Story 1

```bash
# Three duplicate-helper removals can run in parallel:
Task: "Drop _summarize_schema in agent/src/discogs_agent/graph/nodes/code_generator.py"
Task: "Drop _summarize_schema in agent/src/discogs_agent/graph/nodes/query_understanding.py"
Task: "Drop _summarize_schema in agent/src/discogs_agent/tools/query_classifier.py"

# Four prompt edits can run in parallel:
Task: "Replace tables_summary with schema_context_block in agent/src/discogs_agent/prompts/router.md"
Task: "Replace tables_summary with schema_context_block in agent/src/discogs_agent/prompts/query_understanding.md"
Task: "Replace tables_summary with schema_context_block in agent/src/discogs_agent/prompts/code_generator.md"
Task: "Replace tables_summary with schema_context_block in agent/src/discogs_agent/prompts/repair_code.md"

# Tests can be authored in parallel after the impl lands:
Task: "Golden test for 10 canonical styles in agent/tests/golden/test_canonical_styles.py"
Task: "Stub LLM SQL-generation branch in agent/src/discogs_agent/llm/stub.py"
Task: "Extend test_query_classifier with the Techno-routes-to-simple case"
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1 (Setup): T001–T003 → green baseline.
2. Phase 2 (Foundational): T004–T013 → schema context is enriched, migration applied.
3. Phase 3 (US1): T014–T024 → "Show the evolution of Techno releases over time" returns real data.
4. **STOP and demo**: this is the user-visible fix. SC-001 is verifiable.
5. Phases 4/5/6 are quality additions that can land in subsequent commits.

### Incremental Delivery

1. Foundation (Phases 1+2) → no user-visible change yet, but tests for the schema shape pass.
2. + US1 (Phase 3) → MVP, demoable. SC-001.
3. + US3 (Phase 5) → empty-result UX is correct. SC-002.
4. + US2 (Phase 4) → trend-question grain is right. SC-005.
5. + US4 (Phase 6) → structural test coverage. SC-003, SC-004.
6. Polish (Phase 7) → README/quickstart smoke.

### Parallel Team Strategy

If two engineers are available:

1. Both finish Phase 2 together (T004–T013).
2. Engineer A: US1 (Phase 3) — prompt edits + golden styles.
3. Engineer B: US3 (Phase 5) — chart_validator + empty-result handling.
4. Either can pick up Phase 4 (US2) and Phase 6 (US4) — they're tests.

---

## Notes

- Test backend = stub (`LLM_BACKEND=stub`) for everything in the test suite. Live OpenAI calls are reserved for Phase 7 smoke (T043, T044).
- All prompt edits are content-only — they MUST NOT remove the existing safety/forbidden-tables/forbidden-imports sections from `code_generator.md`.
- The renderer in T007 is the new shared utility; T014–T016 remove the three duplicate `_summarize_schema` helpers, but they all leaned on the same shape, so the new function is a drop-in replacement.
- The migration in T011 is the ONLY Postgres change in this feature. Verify it via `agent_runs.status` `\d` output before merging.
- `succeeded_empty` is NOT a failure. Dashboards that filter `status LIKE 'failed_%'` continue to exclude it correctly. Dashboards that count `status = 'succeeded'` will under-count by the empty-result share — flag in the PR description.
- Per the user's flow expectation, the implement phase will follow this tasks file directly via `/speckit-implement`.
