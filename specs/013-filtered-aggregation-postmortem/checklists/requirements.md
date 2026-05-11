# Specification Quality Checklist: Filtered-aggregation postmortem — sandbox OOM observability + glossary follow-on

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
  - **Caveat (intentional)**: this is a postmortem-style back-fill of two operational fixes already partially implemented (012's prior round). The spec necessarily names existing module paths (`sandbox/runner.py:137`, `chart_validator.py:58–69`, `_DOMAIN_GLOSSARY` entry #3, etc.) to anchor where the changes land. This is consistent with how 006, 009, 010, and 012 specs read in this repo — Principle VII demands the spec be honest about what code surface it amends. The spec does NOT prescribe HOW to write the fix; only WHAT the fix must do and WHERE the touched surface lives.
- [x] Focused on user value and business needs
  - US1 explicitly grounds in operator triage time + end-user message clarity.
  - US2 grounds in "the agent answers a real user's question successfully" (Demo Day blocker).
- [x] Written for non-technical stakeholders
  - Two clearly-numbered user stories with plain-English "why this priority" + given/when/then scenarios.
  - The technical "Context" section is labeled as context and can be skipped; the user stories and success criteria are readable without it.
- [x] All mandatory sections completed
  - User Scenarios & Testing ✓ (US1, US2, Edge Cases)
  - Requirements ✓ (FR-001 through FR-015)
  - Success Criteria ✓ (SC-001 through SC-008)
  - Assumptions ✓ + Out of Scope ✓ + Dependencies ✓ (optional but present and informative)

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
  - Two clarifying questions were resolved interactively before the spec was written (release_unique_view framing → Option C; Q1 description fix → fold in). No deferred clarifications.
- [x] Requirements are testable and unambiguous
  - Each FR names a specific file, function, or string and what changes about it.
  - FR-005 (determinism) is explicit; FR-007 (carve-out preservation) names the literal syntactic form.
- [x] Success criteria are measurable
  - SC-001/003/004/007/008 are grep-or-replay verifiable.
  - SC-002 is a single end-to-end run check.
  - SC-005/006 are described as inspection criteria rather than numeric thresholds — acceptable because they're about presence/absence of named values in run records.
- [x] Success criteria are technology-agnostic (no implementation details)
  - **Caveat (intentional)**: SC-001 names `agent_tool_calls.output_json.exception_type` and SC-008 names a specific contract file path. These are observable artifacts of the system already deployed (not new implementation choices); 012's success criteria use the same pattern. The spec is consistent with the repo's house style for back-fills.
- [x] All acceptance scenarios are defined
  - US1: three scenarios covering the OOM-kill, the harness-timeout-not-regressed, and the legitimate-Python-exception-not-mislabeled cases.
  - US2: three scenarios covering the failing query (Depeche Mode), the carve-out spot-check, and the rendered-glossary inspection.
- [x] Edge cases are identified
  - Five edge cases listed: signal-other-than-SIGKILL, view-in-CTE-then-joined, repair-loop-context, regression-on-curated-questions, non-OOM-Python-exceptions, AND the explicitly-acknowledged unresolved gap (SUM/AVG-over-release-numerics).
- [x] Scope is clearly bounded
  - Out of Scope section enumerates seven specific exclusions and points each to a successor or rationale.
- [x] Dependencies and assumptions identified
  - Dependencies section lists exact surgical sites + predecessor (012) + successor (provisional 014).
  - Assumptions section covers infra, signal semantics, constitution compliance, and the explicitly-acknowledged unresolved gap.

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
  - Each FR maps to one or more SC items + at least one acceptance scenario in the user stories.
  - FR-014 (taxonomy contract) and FR-015 (future-spec pointer) are documentation artifacts; their "acceptance" is "the document exists with the prescribed content."
- [x] User scenarios cover primary flows
  - The two primary flows are (a) operator triage of a failed run and (b) end-user query through the agent. Both are covered.
- [x] Feature meets measurable outcomes defined in Success Criteria
  - Each user story's "Independent Test" maps to one or more SC items.
- [x] No implementation details leak into specification
  - As above: the spec names *where* the changes land (necessary for a back-fill) but doesn't prescribe *how* to implement them. The exception_type taxonomy is left open ("e.g., `oom_killed` or `sandbox_signaled`") and FR-013 records that the canonical set will be pinned in the contract document, not in the spec.

## Notes

- All checklist items pass on first iteration. No spec updates required before `/speckit-clarify` or `/speckit-plan`.
- Two scope decisions were resolved interactively during spec drafting: the release_unique_view framing (Option C — tighten now + open ETL follow-on) and the Q1 description fix (folded into 013). No outstanding clarifications.
- The spec's "Context: what slipped past 012" section is non-template content; it exists because this is a postmortem-style follow-on where the failure mechanism is non-obvious. Removing it would not change requirements but would force a future reader to reconstruct the diagnosis from the trace JSON in the conversation log.
