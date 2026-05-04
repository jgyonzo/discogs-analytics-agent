# Tasks: 006-bugfix-postmortem

**Input**: Design documents from `specs/006-bugfix-postmortem/`
**Prerequisites**: spec.md, plan.md.

**Tests**: NOT applicable. This feature is doc-only; verification is
`/speckit-analyze` plus a manual citation check (US1's independent
test).

**Organization**: Single phase. All tasks are documentation edits and
can run sequentially or in parallel — they touch independent files.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel.
- **[Story]**: Which user story this task belongs to.
- File paths are absolute against repo root.

---

## Phase 1: Doc back-fill

- [X] T001 [US1] Amend `.specify/memory/constitution.md`: add Principle
  VII (Implementation Discipline) with sub-rules (a) Configuration
  sources, (b) Prompt-authoring discipline, (c) Read-only runtime
  mechanics. Update Sync Impact Report. Bump version 1.1.0 → 1.2.0.
  Replace all "Principles I–VI" with "I–VII". Update "Last Amended"
  line to today's date.
- [X] T002 [P] [US1] Amend `specs/004-agent-v1/contracts/tools.md` §2.6
  (`cost_logger`): add a "Caller contract" subsection citing Principle
  VII.a, requiring `model_name` to come from `settings.CHEAP_MODEL` /
  `settings.STRONG_MODEL` / `state["route"].selected_model`.
- [X] T003 [P] [US1] Amend
  `specs/004-agent-v1/contracts/code-generation.md` §1 template: update
  the `duckdb.connect()` call to include
  `config={"temp_directory": "/tmp/duckdb"}`. Update §1.1 requirement
  #4 to require both kwargs and cross-reference `research.md R-14` +
  Principle VII.c.
- [X] T004 [P] [US1] Add R-14 to `specs/004-agent-v1/research.md`:
  "DuckDB read-only mount mechanics & spill". Document the
  adjacent-`.tmp/` spill, the `temp_directory` connect-config
  mitigation, why connect-config and not PRAGMA, and rejected
  alternatives. Update the "Summary of resolved unknowns" table.
- [X] T005 [P] [US1] Add a "Consumer rules" section to
  `specs/005-agent-schema-context/contracts/schema-context.md` (before
  "Backwards compatibility"). Cite Principle VII.b. List the forbidden
  prose patterns and what prompts MAY still contain.
- [X] T006 [US1] Create the `006-bugfix-postmortem` feature dir
  (`spec.md`, `plan.md`, `tasks.md`). No `research.md` or
  `data-model.md`.
- [X] T007 [US2] Run `/speckit-analyze` against `006-bugfix-postmortem`
  and confirm zero new violations across the amended files. If
  violations are reported, file follow-up tasks below.

  **Result (2026-05-04)**: zero CRITICAL/HIGH/MEDIUM findings. Three
  LOW findings (empty `contracts/` dir removed; T007 self-checked;
  constitution forward-reference kept) addressed in the same commit.
  Coverage 100% (9/9 requirements mapped).

---

## Verification (US1 independent test)

For each of the three named incidents in `spec.md` Background, walk
the constitution + amended contracts and confirm a citable clause
forbids the pattern:

- **Incident 1** (hardcoded model name) → Constitution VII.a +
  `004/contracts/tools.md §2.6` "Caller contract".
- **Incident 2** (router-prompt prose drift) → Constitution VII.b +
  `005/contracts/schema-context.md` "Consumer rules".
- **Incident 3** (DuckDB temp_directory on `:ro`) → Constitution VII.c
  + `004/research.md R-14` + `004/contracts/code-generation.md §1.1`
  requirement #4.

A future reviewer encountering a regression of any kind MUST be able
to point at the specific clause without re-arguing the case.
