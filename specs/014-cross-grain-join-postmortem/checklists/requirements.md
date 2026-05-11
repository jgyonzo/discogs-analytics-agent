# Specification Quality Checklist: Cross-grain join postmortem — 009 hint update + static forbidden-join enforcement

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
  - **Caveat (intentional)**: this is a postmortem-style follow-on where the spec necessarily names existing code surfaces (`_render_join_graph` at `schema.py:198–262`, `sql_safety_checker.py`, the integration golden path) to anchor where the changes land. Same pattern as 012's and 013's specs in this repo. The spec does NOT prescribe HOW to implement (e.g., it explicitly leaves the regex-vs-AST choice open for US2 and the strict-vs-soft handling of `main_release_id` open as an implementation choice).
- [x] Focused on user value and business needs
  - US1 directly frames against the reported user-facing bug ("top 5 artists" returning meaningless results).
  - US2 frames against operator triage + future-bug containment.
- [x] Written for non-technical stakeholders
  - Two clearly-numbered user stories with given/when/then scenarios + plain-English "Why this priority" sections.
  - The technical "Context" section is labeled and can be skipped; user stories + success criteria are readable standalone.
- [x] All mandatory sections completed
  - User Scenarios & Testing ✓ (US1, US2, Edge Cases)
  - Requirements ✓ (FR-001 through FR-018)
  - Success Criteria ✓ (SC-001 through SC-009)
  - Assumptions ✓ + Out of Scope ✓ + Dependencies ✓

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
  - The two open implementation choices (regex vs. AST for US2; strict-vs-soft for `main_release_id`) are explicitly left as implementation discretion in the spec text. They are not deferred clarifications — they are deliberate flexibility.
- [x] Requirements are testable and unambiguous
  - Each FR names a specific file, function, line range, or string and what changes about it.
  - FR-002 names exact suggested wording for the cross-reference note.
  - FR-009 lists the forbidden-pair set with table.column granularity.
  - FR-010 specifies alias resolution explicitly.
- [x] Success criteria are measurable
  - SC-001/002/003/004/005/006/007/008 are grep-or-replay verifiable.
  - SC-009 quantifies expected test count (≥148 passed, 2 skipped — pre-014 baseline 143 + at least 5 new).
- [x] Success criteria are technology-agnostic (no implementation details)
  - **Caveat (intentional)**: SC-006/007 name strings to grep against (the OLD line that must NOT appear; the NEW line that MUST appear). This is consistent with 012/013's house style for postmortem-style specs where the wording IS the load-bearing artifact.
- [x] All acceptance scenarios are defined
  - US1: four scenarios — triggering question, rendered hint section, glossary unchanged, spot-check carve-out.
  - US2: five scenarios — triggering case rejected, label-bridge variant rejected, legitimate join passes, repair-prompt visibility, conditional on `has_master_fact`.
- [x] Edge cases are identified
  - Seven edge cases: table aliases, CTE-indirection (acknowledged gap), `main_release_id` semantic nuance, 013 must not regress, conditional rendering match, multi-CTE chains, SQL comments.
- [x] Scope is clearly bounded
  - Out of Scope section enumerates five exclusions and points each to rationale or successor.
- [x] Dependencies and assumptions identified
  - Dependencies section lists exact surgical sites + predecessor specs (009, 013) + successor (renumbered to 015).
  - Assumptions section covers `release_fact` traversal sufficiency, regex coverage, list exhaustiveness, and constitution compliance.

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
  - Each of FR-001 through FR-018 maps to one or more SC items + acceptance scenarios in US1 or US2.
  - FR-015 through FR-017 (contract amendments) map to the contracts/ docs that will be written in /speckit-plan.
  - FR-018 (admin renumbering) is verifiable by SC-008.
- [x] User scenarios cover primary flows
  - Two primary flows: (a) user asks a master→artist question and gets a correct answer (US1); (b) the safety net catches a forbidden-join hallucination at safety-check time (US2). Both are covered.
- [x] Feature meets measurable outcomes defined in Success Criteria
  - Each user story's "Independent Test" maps to one or more SC items.
- [x] No implementation details leak into specification
  - Per Content Quality caveat: the spec names *where* changes land (necessary for a back-fill) but doesn't prescribe *how* to implement. The regex-vs-AST choice and the strict-vs-soft handling of `main_release_id` are explicitly left to implementation.

## Notes

- All checklist items pass on first iteration. No spec updates required before `/speckit-plan`.
- Three interactive clarifications resolved during spec drafting:
  - Spec number: 014 (next available; the previously-reserved 014 for the ETL fix is being bumped to 015 via FR-018).
  - Short name: `cross-grain-join-postmortem` (parallel to 012 `catalog-aggregation-postmortem` and 013 `filtered-aggregation-postmortem` — three postmortems in a row, each catching a new bug class).
  - Priority split: US1=P1 (the immediate fix for the reported bug), US2=P2 (durable safety net; not strictly required to close the reported bug but closes the bug class).
- The spec's "Context: a 013-induced regression of 009's safety net" section is non-template content; it exists because this is a postmortem-style follow-on where the failure mechanism (the cross-section contradiction between 009 and 013) is non-obvious. Removing it would force a future reader to reconstruct the diagnosis from conversation logs.
