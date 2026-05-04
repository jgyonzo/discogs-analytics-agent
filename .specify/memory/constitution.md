<!--
SYNC IMPACT REPORT
- Version change: 1.1.0 → 1.2.0
- Bump rationale: Added Principle VII ("Implementation Discipline") with
  three sub-rules — (a) Configuration sources, (b) Prompt-authoring
  discipline, (c) Read-only runtime mechanics. Each codifies a recurring
  silent-failure mode that surfaced during 005-agent-schema-context and
  was post-mortemed in 006-bugfix-postmortem. Updated workflow/governance
  references from "Principles I–VII" to "Principles I–VIII". MINOR per the
  constitution's own policy (new principle added; no existing principle
  redefined or removed).
- Modified principles:
  * (none redefined. Principle VII added.)
- Added sections:
  * Core Principles → VII. Implementation Discipline
- Removed sections: none
- Templates requiring updates:
  * .specify/templates/plan-template.md          ✅ aligned (Constitution
    Check is a generic placeholder resolved per-feature)
  * .specify/templates/spec-template.md          ✅ aligned
  * .specify/templates/tasks-template.md         ✅ aligned
  * .specify/templates/checklist-template.md     ✅ aligned
  * CLAUDE.md                                    ✅ aligned
- Prior history:
  * 1.1.0 (2026-04-25) — added Principle VI (Two Components, One Contract)
    and expanded Technical Constraints.
  * 1.0.0 (2026-04-25) — first ratified constitution; Principles I–V plus
    Technical Constraints, Development Workflow & Quality Gates, Governance.
- Follow-up TODOs: none.
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

### VI. Two Components, One Contract

This repository hosts two independently deployable components:

- **`etl`** — a local-first batch tool that produces the published DuckDB
  artifact from Discogs XML dumps. Runs on a developer laptop.
- **`agent`** — a containerized analytics agent service that answers
  natural-language questions over the published DuckDB. Targets AWS for
  deployment.

The two components are coupled **only** through the published DuckDB artifact
and the table contracts described in Principle V. Specifically:

- The agent MUST consume DuckDB tables/views. It MUST NOT read raw XML,
  staging Parquet, or clean Parquet directly.
- The agent MUST NOT import code from the ETL package, and the ETL MUST NOT
  import code from the agent package. Each component MUST run end-to-end
  without the other component's process.
- Each component MUST live under its own top-level directory with its own
  dependency manifest (e.g., its own `pyproject.toml` / `requirements.txt`).
  Shared utilities, if introduced later, MUST be justified rather than
  assumed and MUST live in a clearly named shared package — not smuggled
  through cross-component imports.
- A change that alters the DuckDB schema is a cross-component change and
  MUST follow Principle I (contract-first): update the contract, the
  producer (ETL), the consumer (agent), and the relevant DQ checks within
  the same change set.

**Rationale:** The two components have fundamentally different runtime
shapes — slow batch on a laptop vs. an online container on AWS. Conflating
them would force one runtime's constraints onto the other and would couple
deploy cycles that have no reason to be coupled. Treating the published
DuckDB as the only contact surface keeps both components free to evolve
within their own envelope.

### VII. Implementation Discipline

Three correctness disciplines apply to every code path in the agent
component. Each codifies a recurring silent-failure mode and was added
after a documented incident (see `specs/006-bugfix-postmortem/`).

**(a) Configuration sources.** Model identifiers, file paths, timeouts,
retry counts, token budgets, and feature flags MUST be sourced from
`settings` (env-driven configuration loaded via `pydantic-settings`) or
graph state (LangGraph state propagated through nodes). Hardcoded
literals for these values are forbidden. The failure mode this prevents:
metadata fields drift away from the value the runtime actually uses
(e.g. a `cost_logger` row with `model_name="gpt-4o-mini"` baked in,
while the underlying call already follows `settings.CHEAP_MODEL` and
the operator overrode that env var).

**(b) Prompt-authoring discipline.** Prompt templates MUST embed catalog
schema information — table names, grains, columns, sample values, the
domain glossary — only via the dynamically-rendered
`{schema_context_block}` placeholder produced by `read_schema_context()`.
Static prose inside a prompt that *describes* what tables exist, what
grain they have, what values they contain, or what the catalog does or
does not include is forbidden. The failure mode this prevents: a prompt
file claims "the available data is RELEASE-LEVEL" while the rendered
block already lists `master_fact` with master grain — the LLM gets a
contradictory mix and the prompt drifts whenever the published schema
evolves.

**(c) Read-only runtime mechanics.** When a runtime constraint declares
a resource read-only (e.g. the published DuckDB mounted `:ro`,
filesystem jails, immutable rootfs), the constraint's *consequences*
MUST be documented alongside it: which operations the runtime would
otherwise perform that require write access, and how each is mitigated.
Declaring "read-only" without surfacing its mechanics leaves the next
code path to discover the failure mode by accident. The failure mode
this prevents: DuckDB's default spill location is `<dbfile>.tmp/`
adjacent to the database file; on a `:ro` mount this fails with
`Read-only file system`, and any GROUP BY / sort / hash-join that
overflows memory silently degrades.

**Rationale:** All three disciplines guard against silent failures —
wrong model in the cost ledger, wrong genre in prompt prose, blank
charts from suppressed spill errors. Each rule has a named past
incident; the discipline keeps the failure mode from recurring on the
next feature. These are correctness properties of the agent runtime,
not stylistic preferences.

## Technical Constraints

### Components & runtime targets

- **ETL:** Python, runs locally on a developer laptop (macOS/Linux). Project
  ships with `.venv/`. There is no cloud runtime for the ETL in v1.
- **Agent:** Containerized service deployed to AWS. The exact AWS service
  (e.g., ECS/Fargate, App Runner, EC2, Lambda), the agent framework, the
  model provider, and the code-execution sandboxing strategy are deliberately
  **not** decided here — they will be settled in the agent's own initial
  spec and a subsequent amendment to this constitution.

### Data layer

- **Stack:** Parquet for canonical intermediate and final outputs; DuckDB as
  the embedded analytical engine consumed by the agent. The choice of
  Parquet + DuckDB is fixed for v1.
- **Inputs:** Local Discogs XML dumps under `data/raw/discogs/{snapshot_id}/`.
  Automated download from Discogs is an explicit non-goal for v1.
- **Outputs:** Outputs MUST follow the directory layout in the initial ETL
  spec (`data/staging/{run_id}/`, `data/clean/{run_id}/`,
  `data/analytics/{run_id}/`, `data/published/duckdb/discogs.duckdb`).

### Boundary artifact

- The agent reads `data/published/duckdb/discogs.duckdb` (or an equivalent
  artifact location once the agent's deployment is specified — e.g., a
  bundled-into-image copy, an S3-fetched copy, or a mounted volume; chosen
  in the agent spec). It MUST NOT read raw XML, staging Parquet, or clean
  Parquet at query time.
- The published DuckDB is the only contract surface between the components
  (Principle VI).

### Secrets

- API keys (LLM provider, AWS credentials), tokens, and personal config
  files MUST NOT be committed. `.env` is gitignored at the repo root and
  MUST stay so. Local development reads secrets from `.env`; deployed
  agent runtimes MUST read secrets from the deploy target's secret store
  (e.g., AWS Secrets Manager, SSM Parameter Store) — confirmed in the
  agent's deployment plan.
- A committed file containing live credentials is a critical violation
  and MUST be remediated by rotation, not just deletion.

### Repository layout

- The repo is a monorepo. Each component lives under its own top-level
  directory (working names `etl/` and `agent/`; final names confirmed at
  the first `/speckit-specify` for each component). Each directory owns
  its dependency manifest, its tests, and its packaging.
- `data/` (raw, staging, clean, analytics, published, manifests, logs) is
  shared between components but is gitignored except for any small
  fixtures explicitly added under e.g. `tests/fixtures/`.
- `docs/` and `specs/` (Spec Kit feature specs) sit at the repo root.

### Scope guardrails

- **ETL v1:** `release_fact` and its bridges only. `master_fact`,
  `artist_dim`, `release_genre_bridge`, `company_bridge`, dashboards, UI,
  RAG, and AWS execution of the ETL are explicit non-goals for v1 and
  MUST NOT be smuggled into v1 features without an amendment to this
  constitution or an explicit scope decision recorded in the relevant
  feature spec.
- **Agent v1:** intentionally undefined here. Scope is deferred to the
  agent's own initial spec. Until that spec exists, plans MUST NOT make
  binding decisions about the agent beyond the Principle VI/Boundary
  artifact constraints.

## Development Workflow & Quality Gates

- **Spec-driven flow:** Non-trivial changes follow the Spec Kit cycle —
  `/speckit-specify` → (optional `/speckit-clarify`) → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`. Each phase produces artifacts
  under `specs/<feature>/` and is committed before the next phase.
- **Plan gate:** Every plan MUST include a Constitution Check section that
  evaluates the proposed work against Principles I–VII and the constraints
  above. Plans MUST also state which component(s) the work touches —
  ETL, agent, or both — so reviewers can apply the right constraints.
  Violations MUST be either eliminated or recorded in the plan's
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

**Compliance review:** Plans and PRs that introduce or modify pipeline or
agent behavior MUST cite the principles they engage with. Reviewers MUST
reject changes that violate Principles I–VII without an accepted amendment
or a recorded, justified exception in Complexity Tracking. Recurring
exceptions in the same area are a signal the principle should be amended,
not bypassed.

**Runtime guidance:** Day-to-day implementation guidance for AI assistants
lives in `CLAUDE.md` and the active feature plan under `specs/<feature>/`.
Those documents MUST be consistent with this constitution; on conflict, this
constitution prevails.

**Version**: 1.2.0 | **Ratified**: 2026-04-25 | **Last Amended**: 2026-05-04
