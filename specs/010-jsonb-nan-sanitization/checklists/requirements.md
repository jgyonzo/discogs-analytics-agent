# Specification Quality Checklist: JSONB NaN sanitization

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-08
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### Validation pass — 2026-05-08

- **Tone caveat**: This is an agent-internals bugfix (same as 009). "Non-technical stakeholders" is interpreted as "the spec is readable by someone who knows the project but doesn't know SQLAlchemy's TypeDecorator API." User-visible behavior (queries succeed end-to-end) and the contract surface (JSONB inputs MUST be RFC-8259-compliant) are described; specific Python signatures and type-decorator hook ordering belong in the plan.

- **Stack-shaped phrases that remain are intentional**: paths to the producer (`agent/src/discogs_agent/persistence/`) and the test target are present because (a) the feature is by definition an agent-internal fix, (b) the contract surface IS `004/contracts/postgres-schema.md`, and (c) the JSONType wrapper is a real, named SQLAlchemy artifact. They are observable from the maintainer's perspective; they don't bind a specific implementation choice (TypeDecorator vs. event-hook vs. per-Repo).

- **Reproducer is named with run id**: `4b0f6979-71f8-41dc-8d79-204933621f3a` from the user's docker-compose log is the stable identifier.

- **Constitutional analog is explicit**: VII.c was declared after 006/007 for the read-only DuckDB / RLIMIT_FSIZE class. This bug is the **write-side** counterpart: Postgres JSONB declares "RFC-8259 only" and that constraint's consequences must be documented alongside it. The feature operationalizes the analogous discipline at the persistence-write boundary without requiring a new constitution principle.

- **No clarification markers**: All edge cases (idempotence, nested structures, SQLite stratum, tuples) have explicit Assumptions/Edge-Cases entries.

### Items requiring follow-up at plan time

- Plan must decide between (a) `TypeDecorator` wrapping `JSONType` (single chokepoint, runs on every JSONB column on both Postgres and SQLite, hooks at the type level — recommended in spec Assumptions), (b) SQLAlchemy event hook on `before_insert`/`before_update`, (c) per-Repo `create()` method calls. Trade-offs: (a) is most general; (b) doesn't fire on raw SQL `INSERT` (none in current code path but possible); (c) is per-call-site discipline that VII.b-style enforcement would warn against.
- Plan must propose the exact prose for the new §7 of `004/contracts/postgres-schema.md`. The spec only says it must exist and document the JSONB input invariant — the plan picks wording.
- Plan must decide whether the integration test runs against (a) only the SQLite stratum (cheap, deterministic, but doesn't exercise the actual Postgres JSONB enforcement), (b) a Postgres test fixture (slow but production-faithful), or (c) both. The user-facing failure is Postgres-specific; SQLite would silently swallow NaN. So at minimum the test asserts on the *sanitizer output* (deterministic) and ideally on a real Postgres write (production-faithful).
