# Implementation Plan: 006-bugfix-postmortem

**Spec**: [spec.md](./spec.md)
**Status**: Draft
**Component(s) touched**: documentation only — `.specify/memory/` and
`specs/004-agent-v1/`, `specs/005-agent-schema-context/`. No code under
`agent/` is modified by this feature.

## Constitution Check

This feature *amends* the constitution rather than complying with it,
which is the only legitimate way to add a new principle. The amendment
itself follows the constitution's own Governance / Versioning policy
(MINOR bump, Sync Impact Report, dependent-template review).

Principles I–VI: not engaged by this feature.
Principle VII (added by this feature): self-consistent — the new
clauses each codify a recurring failure mode with a named incident
attached.

## Approach

Five doc edits + one new feature dir + one consistency check.

### Edit 1 — Constitution

`.specify/memory/constitution.md` — add Principle VII (Implementation
Discipline) with three sub-rules, bump version 1.1.0 → 1.2.0, update
Sync Impact Report, refresh "Principles I–VI" → "Principles I–VII"
references in the Workflow and Governance sections.

### Edit 2 — `004/contracts/tools.md`

Add a "Caller contract" subsection inside §2.6 (`cost_logger`)
requiring `model_name` to come from `settings.CHEAP_MODEL` /
`settings.STRONG_MODEL` / `state["route"].selected_model`. Cites
Principle VII.a.

### Edit 3 — `004/contracts/code-generation.md`

Update §1 template — `duckdb.connect()` call now includes
`config={"temp_directory": "/tmp/duckdb"}`. Update §1.1 requirement #4
to require both kwargs. Cross-reference `research.md R-14` and
Principle VII.c.

### Edit 4 — `004/research.md`

Add R-14: DuckDB read-only mount mechanics & spill. Document the
adjacent-`.tmp/` spill behavior, the `temp_directory` connect-config
mitigation, why connect-config and not PRAGMA, and which alternatives
were rejected. Update the "Summary of resolved unknowns" table.

### Edit 5 — `005/contracts/schema-context.md`

Add a "Consumer rules" section (before "Backwards compatibility")
codifying the prompt-prose ban. Cites Principle VII.b. Lists what is
forbidden vs. what prompts may still contain.

### Edit 6 — Create `006/` feature dir

`spec.md`, this `plan.md`, and `tasks.md`. No `research.md` or
`data-model.md` — neither is needed for a documentation back-fill.

### Verification — `/speckit-analyze`

Run `/speckit-analyze` against `006-bugfix-postmortem`. Expect zero
new violations.

## Risks & rollback

- **Risk**: Amending three older spec files invites merge conflicts
  if those branches are still being amended elsewhere. **Mitigation**:
  005 is in MR-4 awaiting merge but its branch is now closed for new
  feature work; 004 has been merged. The amendments are additive
  (new section, new subsection, new R-section) — no existing text is
  changed except the "I–VI" → "I–VII" reference and the constitution
  version line.
- **Rollback**: Pure doc edits. Revert the commit if the amendments
  introduce confusion. No data loss, no code surface affected.

## Out of scope

- Any code change in `agent/`.
- Amending `005/tasks.md` retroactively (the historical record stays).
- New tests (this is doc hygiene; the bug fixes already have tests
  via the modified files in `c2000e4`/`c3699a8`/`d2b02f3`).
