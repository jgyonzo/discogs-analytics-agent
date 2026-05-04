# Feature Specification: Post-mortem & spec back-fill for three 004/005 bugs

**Feature Branch**: `006-bugfix-postmortem`
**Created**: 2026-05-04
**Status**: Draft
**Input**: User description: "look on the speckit artifacts generated for
004-agent-v1 and 005-agent-schema-context and find gaps or ambiguity that
lead to the generation of the previous fixed bugs."

## Background — what happened

While exercising the agent built by features `004-agent-v1` and
`005-agent-schema-context`, three independent bugs surfaced in production:

1. **`router_node` cost-log mislabel.** `router.py:27` hardcoded
   `model_name="gpt-4o-mini"` in its `cost_logger` call; the underlying
   `query_classifier` actually invoked `settings.CHEAP_MODEL`. Overriding
   `CHEAP_MODEL` in `.env` left the cost-log row reporting the wrong
   model. Fixed in commit `c2000e4`.

2. **Router-prompt prose drift.** `prompts/router.md` claimed *"the
   available data is RELEASE-LEVEL: counts, styles, formats, countries,
   decades, labels, artists, master/version links"* — internally
   contradictory once `master_fact` became optional in 005, since
   `master_fact` has master grain, not release. The static prose
   duplicated information already rendered into `{schema_context_block}`
   and could not stay in sync. Fixed in commit `c3699a8`.

3. **DuckDB temp_directory on `:ro` mount.** `_collect_sample_values`'s
   GROUP BYs failed with `IO Error: Read-only file system` because
   DuckDB tries to spill to `<dbfile>.tmp/` adjacent to the database file
   — and the published DuckDB volume is mounted `:ro`. The error was
   silently swallowed, dropping `country`, `primary_genre`, and
   `primary_format_group` from the schema-context payload. Same risk
   applied to LLM-generated sandbox code. Fixed in commit `d2b02f3`.

All three were patched directly in code without going through the SDD
loop. This feature is the back-fill: capture the lessons in the
constitution and contracts so the next feature inherits the discipline.

## Why each bug shipped — the spec gap

| Bug | Root spec gap |
| --- | --- |
| 1 | `004/contracts/tools.md §2.6` defined `CostInput.model_name: str` but never said where the value should come from. Other nodes happened to use `settings.CHEAP_MODEL` correctly; the contract did not require it. |
| 2 | `005/tasks.md` T017–T020 said "swap the placeholder, keep all other prompt structure intact" — preserving the static prose that 005's own work made redundant. No contract clause forbade duplicating schema prose. |
| 3 | `004/research.md R-02` and `004/plan.md` declared the `:ro` mount as a security control. Neither documented DuckDB's adjacent `<dbfile>.tmp/` spill behavior or the mitigation. Pure domain-knowledge gap. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Future agent code paths inherit the three disciplines (Priority: P1)

A future feature touches the agent runtime — adds a new node, a new
prompt, or a new code path that opens DuckDB. The implementer reads
the constitution and the affected contracts before writing code. The
three disciplines (configuration sources, prompt-authoring discipline,
read-only runtime mechanics) appear as named, citable rules with a
named past incident attached to each. Reviewers can reject violating
PRs by citing the principle, not by re-arguing the case from scratch.

**Why this priority**: This is the entire reason for the back-fill.
If the disciplines are not citable, the next bug repeats.

**Independent Test**: Manual review — a fresh reader of the
constitution and contracts can answer, for each of the three past
incidents, *"which clause would have prevented it?"* and point to the
exact section.

**Acceptance Scenarios**:
1. **Given** the constitution at v1.2.0, **When** a reviewer encounters
   a PR that hardcodes `model_name="gpt-4o-mini"` in any node's
   `cost_logger` call, **Then** the reviewer can cite Principle VII.a
   ("Configuration sources") to reject it without writing original
   prose.
2. **Given** `005/contracts/schema-context.md` "Consumer rules"
   section, **When** a reviewer encounters a prompt edit that adds
   prose like *"the available data is …"* describing tables, **Then**
   the reviewer can cite that section to reject it.
3. **Given** `004/research.md R-14`, **When** a future feature opens a
   new `duckdb.connect()` call site, **Then** the implementer is
   directed to include `config={"temp_directory": "/tmp/duckdb"}` and
   knows why.

### User Story 2 — `/speckit-analyze` reports zero new inconsistencies (Priority: P2)

After the back-fill amendments land, running `/speckit-analyze` against
006 produces no consistency violations across `006/spec.md`,
`006/plan.md`, `006/tasks.md`, and the amended files in 004 and 005.

**Why this priority**: Catches accidental contract drift introduced by
this very back-fill. Lower than US1 because US1 is the substantive
deliverable and US2 is the meta-check.

**Independent Test**: Run `/speckit-analyze`; expect a clean report.

## Functional Requirements

- **FR-001**: Constitution MUST add Principle VII (Implementation
  Discipline) covering (a) configuration sources, (b) prompt-authoring
  discipline, (c) read-only runtime mechanics. Version bump to 1.2.0.
- **FR-002**: `004/contracts/tools.md §2.6` MUST add a "Caller
  contract" subsection requiring `model_name` to come from settings or
  state, citing Principle VII.a.
- **FR-003**: `004/contracts/code-generation.md §1.1` MUST update the
  generated-code template to include `config={"temp_directory":
  "/tmp/duckdb"}` in the `duckdb.connect()` call and document the
  requirement, citing Principle VII.c and `research.md R-14`.
- **FR-004**: `004/research.md` MUST add R-14 documenting DuckDB's
  spill behavior under `:ro` mount and the temp_directory mitigation.
- **FR-005**: `005/contracts/schema-context.md` MUST add a "Consumer
  rules" section codifying the prompt-prose ban, citing Principle
  VII.b.
- **FR-006**: `/speckit-analyze` against 006 MUST report zero new
  inconsistencies after all amendments land.

## Success Criteria

- **SC-001**: All three named past incidents have a constitution
  clause and a contract clause that, read together, forbid the
  pattern that produced the bug.
- **SC-002**: No code changes ship in 006. The bug fixes already
  shipped in `c2000e4`, `c3699a8`, and `d2b02f3`; 006 is doc-only.
- **SC-003**: Constitution version reaches 1.2.0 with a complete
  Sync Impact Report.

## Out of scope

- Re-implementing or modifying the bug fixes. Those landed.
- Amending `005/tasks.md` retroactively. Tasks are a historical
  record; the going-forward rule lives in the contract.
- New automated tests. Verification is documentary
  (`/speckit-analyze`) and review-process-driven.
