<!--
SYNC IMPACT REPORT
- Version change: (initial) → 1.0.0
- Bump rationale: First ratified constitution; all template placeholders replaced
  with concrete principles, constraints, and governance rules (MAJOR baseline).
- Modified principles:
  * [PRINCIPLE_1_NAME]              → I. Layered, Contract-First Data Architecture
  * [PRINCIPLE_2_NAME]              → II. Streaming, Bounded-Memory Processing
  * [PRINCIPLE_3_NAME]              → III. Reproducible Runs with Manifest & Logs (NON-NEGOTIABLE)
  * [PRINCIPLE_4_NAME]              → IV. Data Quality Gates
  * [PRINCIPLE_5_NAME]              → V. Agent-Friendly Analytics Surface
- Added sections:
  * Technical Constraints (was [SECTION_2_NAME])
  * Development Workflow & Quality Gates (was [SECTION_3_NAME])
- Removed sections: none
- Templates requiring updates:
  * .specify/templates/plan-template.md          ✅ aligned (Constitution Check is
    a generic placeholder resolved per-feature against this file; no static edit
    required)
  * .specify/templates/spec-template.md          ✅ aligned (no principle-driven
    structural changes required)
  * .specify/templates/tasks-template.md         ✅ aligned (task categorization
    neutral; DQ tasks already representable under existing phases)
  * .specify/templates/checklist-template.md     ✅ aligned
  * CLAUDE.md                                    ✅ aligned (delegates to current
    plan; no principle references to update)
  * README.md                                    ⚠ pending (currently the GitLab
    boilerplate; should eventually summarize project + reference this
    constitution, but not blocking)
- Follow-up TODOs: none deferred.
-->

# Discogs ETL & Analytics Agent Constitution

## Core Principles

### I. Layered, Contract-First Data Architecture

The pipeline MUST be organized as discrete layers — `raw` → `staging` → `clean` →
`analytics` → `published` (DuckDB) — and each layer MUST expose an explicit,
documented contract (table name, grain, columns, types, nullability, logical
keys). Downstream layers MUST consume only the documented outputs of upstream
layers; they MUST NOT reach across layers (e.g., `release_fact` MUST NOT join
directly against `clean_release_formats`; it MUST consume `release_format_summary`).
Breaking changes to a published contract MUST be treated as a MAJOR change and
documented before implementation.

**Rationale:** Layer separation is what makes the pipeline reasonable about,
re-runnable, and safe for an LLM agent to consume. Contracts prevent silent
schema drift from breaking generated SQL or downstream analyses.

### II. Streaming, Bounded-Memory Processing

XML inputs MUST be parsed in streaming mode (e.g., iterparse-style), never
loaded whole into memory. Stage writers MUST flush to Parquet in batches.
Transformations MUST be expressible against bounded memory, even when the
source dump is at full Discogs scale (~60 GB releases XML). Any code path
that materializes the full XML, or a full layer, into a single in-process
collection is a violation.

**Rationale:** The release dump is too large for in-memory processing; the
pipeline is designed to run on a developer laptop. Bounded memory is the
load-bearing assumption that makes the project tractable end-to-end.

### III. Reproducible Runs with Manifest & Logs (NON-NEGOTIABLE)

Every pipeline execution MUST be identified by a `run_id` and MUST produce
(a) a manifest at `data/manifests/{run_id}.json` recording inputs (paths,
sizes, checksums), outputs (paths, row counts), per-step durations, status,
and warnings; and (b) a log at `data/logs/{run_id}.log`. Re-running the
pipeline against the same `snapshot_id` and configuration MUST yield logically
equivalent outputs. Steps MUST be individually re-runnable via the CLI; flags
such as `--run-id`, `--snapshot-id`, `--limit-releases`, `--force`, and
`--skip-existing` MUST be supported to enable iteration without re-processing
everything. Ad-hoc, undocumented manual steps as part of producing a published
output are forbidden.

**Rationale:** Without reproducibility, the agent's analytics layer becomes a
black box: there is no way to audit a number, recover from a partial failure,
or distinguish a code bug from a data issue. The manifest is the audit trail.

### IV. Data Quality Gates

Each output layer MUST run the data quality checks defined for it (e.g., uniqueness
of `release_id` in `clean_releases`; `released_date_precision` in the allowed
enum; `format_group` in the allowed enum; at most one `is_primary_*` per release).
Critical failures (uniqueness violations, schema mismatches, contract
violations) MUST fail the run with a non-zero exit code. Non-critical issues
MUST be recorded as warnings in the manifest. New columns or new derivations
MUST be accompanied by new or updated checks in the same change.

**Rationale:** The agent layer trusts upstream invariants — if those invariants
are not actually enforced, the LLM will produce confident but wrong answers.
DQ checks are the contract enforcement mechanism, not nice-to-haves.

### V. Agent-Friendly Analytics Surface

The analytics layer exposed to the agent MUST be intentionally small and
stable: in v1, `release_fact`, `release_artist_bridge`, `release_label_bridge`,
and the `release_unique_view` view in DuckDB. Naming conventions are
load-bearing and MUST be preserved: `is_*_format` flags exist at the
release-x-format grain (`clean_release_formats`); `has_*` flags exist at the
release grain (`release_format_summary`, `release_fact`). Counts of unique
releases MUST be expressible via `COUNT(DISTINCT release_id)` or
`release_unique_view`; new columns or tables MUST NOT introduce row
multiplication that would silently break naive `COUNT(*)` queries. Adding a
new analytics table is a deliberate decision and MUST be justified against
the alternative of a view or an extension to an existing fact.

**Rationale:** The agent generates Python+SQL from natural language; every
extra table, every inconsistent name, every implicit grain change is a place
where the LLM hallucinates or miscounts. Surface minimalism is a correctness
property, not a stylistic one.

## Technical Constraints

- **Stack:** Python (project ships with `.venv/`), Parquet for canonical
  intermediate and final outputs, DuckDB as the embedded analytical engine
  consumed by the agent. The choice of Parquet+DuckDB is fixed for v1.
- **Inputs:** Local Discogs XML dumps under `data/raw/discogs/{snapshot_id}/`.
  Automated download from Discogs is an explicit non-goal for v1.
- **Outputs:** Outputs MUST follow the directory layout in the initial spec
  (`data/staging/{run_id}/`, `data/clean/{run_id}/`, `data/analytics/{run_id}/`,
  `data/published/duckdb/discogs.duckdb`).
- **Scope guardrails (v1):** `release_fact` and its bridges only. `master_fact`,
  `artist_dim`, `release_genre_bridge`, `company_bridge`, RAG, dashboards, UI,
  and AWS execution are explicit non-goals for v1 and MUST NOT be smuggled into
  v1 features without an amendment to this constitution or an explicit scope
  decision recorded in the relevant feature spec.
- **The XML is never queried online:** The agent MUST NOT read raw XML or
  staging Parquet at query time. Its data surface is the published DuckDB
  tables and views described in Principle V.

## Development Workflow & Quality Gates

- **Spec-driven flow:** Non-trivial changes follow the Spec Kit cycle —
  `/speckit-specify` → (optional `/speckit-clarify`) → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`. Each phase produces artifacts
  under `specs/<feature>/` and is committed before the next phase.
- **Plan gate:** Every plan MUST include a Constitution Check section that
  evaluates the proposed work against Principles I–V and the constraints
  above. Violations MUST be either eliminated or recorded in the plan's
  Complexity Tracking with explicit justification before implementation begins.
- **Pipeline change gate:** Any change that touches a layer's output (column
  added/removed, type changed, grain changed, derivation logic changed) MUST
  update (a) the contract section in the relevant feature spec, (b) the data
  quality checks for that layer, and (c) any consumer that depends on the
  changed contract — within the same change set.
- **CLI as the source of truth:** Every pipeline operation that produces or
  modifies a layer MUST be reachable via the documented CLI
  (`python -m discogs_etl.cli ...`). Notebook-only or REPL-only data
  generation that ends up in a published output is forbidden.
- **Sample-first iteration:** New ETL logic MUST be validated against a
  sample run (`--limit-releases`) before being run against the full dump.
  This is a workflow norm, not a code change — the CLI flag enables it.

## Governance

This constitution supersedes ad-hoc conventions. When this document and an
existing practice disagree, this document wins, and the practice is updated
or the constitution is formally amended.

**Amendments:** Proposed changes MUST be made via a pull request (or merge
request) that (a) updates this file, (b) updates the version line below
according to the semantic-versioning policy, (c) updates the Sync Impact
Report at the top, and (d) updates any dependent template or doc the change
affects. Amendments take effect when merged into `main`.

**Versioning policy (this constitution):**
- **MAJOR** — backwards-incompatible governance change, principle removed,
  or principle redefined in a way that invalidates existing plans.
- **MINOR** — a new principle or section added, or material expansion of
  existing guidance.
- **PATCH** — clarifications, wording, typo fixes, non-semantic refinements.

**Compliance review:** Plans and PRs that introduce or modify pipeline
behavior MUST cite the principles they engage with. Reviewers MUST reject
changes that violate Principles I–V without an accepted amendment or a
recorded, justified exception in Complexity Tracking. Recurring exceptions
in the same area are a signal the principle should be amended, not bypassed.

**Runtime guidance:** Day-to-day implementation guidance for AI assistants
lives in `CLAUDE.md` and the active feature plan under `specs/<feature>/`.
Those documents MUST be consistent with this constitution; on conflict, this
constitution prevails.

**Version**: 1.0.0 | **Ratified**: 2026-04-25 | **Last Amended**: 2026-04-25
