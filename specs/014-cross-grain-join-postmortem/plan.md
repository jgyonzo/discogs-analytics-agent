# Implementation Plan: Cross-grain join postmortem — 009 hint update + static forbidden-join enforcement

**Branch**: `014-cross-grain-join-postmortem` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Forward implementation. Triggered by run `2557c2ce-21e2-4838-8790-d54528e8043c` on 2026-05-10 — a 013-induced regression of 009's safety net.

## Summary

Forward implementation, two work streams + one admin task:

1. **US1 (P1) — Cross-grain hint update.** `_render_join_graph` in `agent/src/discogs_agent/duckdb_layer/schema.py` (lines 198–262) currently recommends `release_unique_view` for master → release-grain traversal — the path 013 just forbade. After 014, the hint recommends `release_fact`, removes the `Prefer release_unique_view ... over release_fact` contradicting line, and adds an explicit cross-reference to glossary entry #3. Golden snapshot regenerated; unit-test phrase assertions updated.

2. **US2 (P2) — Static forbidden-join enforcement.** `sql_safety_checker` gains a new pass that scans extracted SQL for predicates of the form `master_fact.<id_col> = release_*_bridge.<id_col>`. The forbidden-pair list is module-level data (matching the rendered list in the schema-context block). Aliases (`mf`, `rab`, etc.) resolved to underlying table names before matching. Emits `SafetyViolation(rule="forbidden_join", detail=<canonical predicate>)` and rejects. Regex-based per Explore findings (sqlparse already a dep; AST upgrade deferred).

3. **Renumbering admin.** 013's `contracts/successor-014-pointer.md` is renamed to `successor-015-pointer.md` because 014 is now this spec; the ETL follow-on bumps to 015. File content updated in the same edit.

Plus three contract amendments: third-round on `005/schema-context.md` cross-grain hint, supersedes part of `009/amendment-005`, extends `004/sql-safety.md` with the new rule.

## Technical Context

**Language/Version**: Python 3.12 (existing agent runtime).
**Primary Dependencies**: existing — `sqlparse` (already used by `sql_safety_checker`), `duckdb`, `pytest`. No new dependencies. The Plan-mode Explore confirmed sqlparse is sufficient for the smallest-diff approach.
**Storage**: published DuckDB (`:ro`) and Postgres for run records. No schema changes — the new `SafetyViolation` rule flows through the existing JSON column.
**Testing**: pytest. New unit tests in `tests/unit/test_sql_safety_checker.py` (at least 5 cases per spec FR-014). Existing schema-context golden regenerated. Existing unit-test `test_schema_context.py:test_join_graph_section_present_when_master_fact_true` will need phrase-assertion updates.
**Target Platform**: Linux container (production), macOS host (dev). The regex-based predicate scan is platform-portable.
**Project Type**: agent component only (Constitution Principle VI). Touches:

- `agent/src/discogs_agent/duckdb_layer/schema.py` (`_render_join_graph` lines 198–262) — FR-001 through FR-005.
- `agent/src/discogs_agent/tools/sql_safety_checker.py` — FR-008 through FR-012 (new pass: `_scan_forbidden_joins`).
- `agent/tests/integration/golden/schema_context_block.txt` — FR-006 (regenerated).
- `agent/tests/unit/test_schema_context.py` — FR-007 (phrase-assertion updates).
- `agent/tests/unit/test_sql_safety_checker.py` — FR-014 (new test cases).
- `specs/005-agent-schema-context/contracts/schema-context.md` — FR-015 (cross-grain hint section).
- `specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md` — FR-016 (supersession note for the hint section; forbidden-joins section unchanged).
- `specs/004-agent-v1/contracts/sql-safety.md` — FR-017 (new rule documented).
- `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` — FR-018 (renamed to `successor-015-pointer.md`; content updated).

**Performance Goals**: no perf-budget change. The forbidden-join scan is O(SQL length) over a small regex set; runs once per generated SQL. The hint rewrite is a wording change with zero runtime impact.

**Constraints**:
- The forbidden-join rule MUST be conditional on `has_master_fact = True` (FR-012, matches the renderer's conditional).
- Adding a new forbidden pair is a contract amendment (FR-009 normative).
- Constitution VII.b: the hint text lives in the dynamically-rendered `{schema_context_block}`. The new safety-checker rule is enforcement, not prose; doesn't touch prompt templates.
- Constitution VII.c-analog: 014 declares the enforcement mechanics alongside the rendered statement (the rule was already named as data; it gains runtime teeth).

**Scale/Scope**: ~5 source files changed in `agent/`, 1 golden regenerated, 2 test modules edited, ~4 documentation files touched. ~1 hour of implementation work, ~1 hour of tests + golden regeneration + manual replay.

## Constitution Check

| Principle | Engaged? | Verdict |
|-----------|----------|---------|
| I — Layered, Contract-First Data Architecture | No | No published-DuckDB schema change. The renumbered ETL follow-on (`successor-015-pointer`) still defers the view's materialization rewrite. |
| II — Streaming, Bounded-Memory Processing | No | Not engaged. |
| III — Reproducible Runs | Indirectly | The new `forbidden_join` rule value appears in `agent_tool_calls.output_json` deterministically per pure-function input. Re-running the same SQL produces the same violation. ✅ |
| IV — Data Quality Gates | No | Not engaged. |
| V — Agent-Friendly Analytics Surface | Yes — *nuance* | Principle V names `release_unique_view` on the surface and says "Counts of unique releases MUST be expressible via `COUNT(DISTINCT release_id)` or `release_unique_view`". Post-013, the view was already narrowed to spot-checks-only in glossary entry #3. 014 further narrows by removing the cross-grain traversal recommendation — but the view remains *on the surface* for spot-checks, and `COUNT(DISTINCT release_id)` (the principle's first-cited path) remains the canonical recommendation. No surface removal; just tightening the recommended traversal shape. ✅ |
| VI — Two Components, One Contract | Yes | Fully inside `agent/`. Zero edits to `etl/` or `frontend/`. The renumbering admin touches `specs/013/` documentation only — no cross-component runtime change. ✅ |
| VII.a — Configuration sources | Yes — *trade-off* | The forbidden-pair list (`master_fact.master_id = release_*_bridge.release_id`, etc.) is a module-level constant in `sql_safety_checker.py`. **Trade-off**: env-driven configuration would invite operator-introduced drift between the rendered block, the contract, and the runtime rule. The list is a *taxonomy* (matches the canonical rendered list); same status as the pre-existing rule names (`"ddl_dml"`, `"read_only_required"`, `"forbidden_table"`, etc.). Adding a new pair is a contract amendment. ✅ |
| VII.b — Prompt-authoring discipline | Yes — load-bearing | The cross-grain hint rewrite (US1) ships through `_render_join_graph` → `{schema_context_block}` — the dynamic renderer is the legitimate channel. No static schema prose is added to any prompt template; the hint text remains in the renderer where 009 placed it. The forbidden-pair list in the safety checker is *enforcement* (executable code), not prompt content; VII.b doesn't apply to it. ✅ |
| VII.c — Read-only runtime mechanics (analog) | Yes — analog | The original VII.c declared the runtime constraint (`:ro` mount) and documented its consequences (DuckDB spill mechanics). 014 is the *enforcement* analog: the forbidden-joins list was already named in the rendered block (009's contribution); 014 declares its runtime consequence (violations are caught at safety-check time). The 004/sql-safety.md amendment (FR-017) is the load-bearing artifact. ✅ |

**Gate result**: PASS. The plan respects Principles I–VII without exception. Two trade-offs (V's surface-narrowing — third round after 012 + 013; VII.a's taxonomy literals — mirrors 013's `oom_killed` precedent) are surfaced inline.

**Component(s) touched**: `agent/` only.

## Project Structure

### Documentation (this feature)

```text
specs/014-cross-grain-join-postmortem/
├── spec.md                                              # Already written
├── plan.md                                              # This file
├── research.md                                          # Phase 0 — implementation choices + wording decisions
├── data-model.md                                        # Phase 1 — taxonomic entities (hint text, forbidden-pair list, rule name)
├── contracts/
│   ├── amendment-005-schema-context.md                  # Cross-grain hint section — third round on 005
│   ├── amendment-009-cross-grain-hint.md                # Supersedes 009's amendment-005 for the hint subsection only
│   ├── amendment-004-sql-safety.md                      # New `forbidden_join` rule documented
│   └── renumbering-013-pointer.md                       # Explicit record of 013's successor-014 → successor-015 rename
├── checklists/
│   └── requirements.md                                  # Already written; all 14 items pass
├── quickstart.md                                        # Phase 1 — verification procedure (replay 2557c2ce + safety-check probes)
└── tasks.md                                             # Phase 2 — `/speckit-tasks` output (NOT created here)
```

### Source Code (this feature — to-be-changed)

```text
agent/src/discogs_agent/duckdb_layer/schema.py              # FR-001 through FR-005 (lines 198–262, _render_join_graph)
agent/src/discogs_agent/tools/sql_safety_checker.py         # FR-008 through FR-012 (new _scan_forbidden_joins pass)
agent/tests/integration/golden/schema_context_block.txt     # FR-006 (regenerated)
agent/tests/unit/test_schema_context.py                     # FR-007 (phrase-assertion updates around lines 152–215)
agent/tests/unit/test_sql_safety_checker.py                 # FR-014 (new test cases — at least 5 added)

specs/005-agent-schema-context/contracts/schema-context.md  # FR-015 cross-grain hint section
specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md  # FR-016 (supersession note for hint section)
specs/004-agent-v1/contracts/sql-safety.md                  # FR-017 (new `forbidden_join` rule)

# Admin (FR-018):
specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md → successor-015-pointer.md  (rename + content update)
```

**Structure Decision**: agent-component-only forward implementation. Mirrors 013's documentation layout exactly (4 contracts under `contracts/`, two of which are new amendments to upstream contracts the predecessor specs already touched, plus one supersession + one admin record). The implementation surface is small (~5 code files + golden + 2 test modules); the documentation surface carries most of the back-fill weight.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Nothing to track. Constitution Check passed with no violations. The two nuances surfaced (Principle V's surface-narrowing third round, VII.a's taxonomy literals) are inline justifications, not violations — both fit within established carve-outs that 012 and 013 already invoked.
