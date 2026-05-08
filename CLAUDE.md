<!-- SPECKIT START -->
Active feature: **010-jsonb-nan-sanitization** — silent-class
bugfix in the agent's persistence layer. A user query that
produced a dataframe with NULL country values triggered
`psycopg.errors.InvalidTextRepresentation: invalid input syntax
for type json: Token "NaN" is invalid`. Pandas converts NULLs to
`float('nan')`; `df.head(20).to_dict("records")` preserves them;
Pydantic `model_dump()` preserves them; psycopg's default
`json.dumps` is `allow_nan=True` (emits non-standard `NaN`
literal); Postgres JSONB rejects per RFC 8259. Five JSONB columns
(`agent_runs.metadata_json`, `agent_threads.metadata_json`,
`agent_tool_calls.input_json`, `agent_tool_calls.output_json`,
`agent_artifacts.metadata_json`) all share the failure surface.

010 closes the gap by adding a sanitizer at the persistence-write
boundary that recursively replaces NaN/Infinity/-Infinity with
None. Single chokepoint via SQLAlchemy `TypeDecorator` (or
equivalent — final placement decided in plan/research) so all
five JSONB columns are protected by one change. The 004 contract
gets a new §7 declaring the JSONB input invariant: every dict
flowing into JSONB MUST be RFC-8259-compliant.

Read this feature's plan and its phase-1 artifacts:

- Spec: `specs/010-jsonb-nan-sanitization/spec.md`
- Plan: `specs/010-jsonb-nan-sanitization/plan.md`
- Research: `specs/010-jsonb-nan-sanitization/research.md`
  (chokepoint placement + test strategy + sanitizer signature)
- Contracts: `specs/010-jsonb-nan-sanitization/contracts/`
  - `amendment-004-postgres-schema.md` — exact prose for the
    new §7 of `004/contracts/postgres-schema.md`
- Quickstart: `specs/010-jsonb-nan-sanitization/quickstart.md`
- Checklist: `specs/010-jsonb-nan-sanitization/checklists/requirements.md`

Reproducer: run `4b0f6979-71f8-41dc-8d79-204933621f3a`,
question *"What are the top 15 countries by number of releases?"*
(curated demo Q4) — or any other agent query whose dataframe
preview legitimately contains NULL cells.

Prior 004-family work (still authoritative):

- `specs/004-agent-v1/` — V1 baseline (graph, API, sandbox, SQL
  safety, generated-code shape, persistence). 010 amends
  `004/contracts/postgres-schema.md`.
- `specs/005-agent-schema-context/` — schema enrichment + sample
  values + glossary + the `succeeded_empty` zero-row guardrail.
  Amended by 009.
- `specs/006-bugfix-postmortem/` — three-bug postmortem and
  Constitution v1.2.0 amendment (Principle VII: Implementation
  Discipline). 010 is structurally another VII.c follow-through
  (write-side counterpart to the read-side mechanics 006/007
  established).
- `specs/007-sandbox-fsize-budget/` — sandbox `RLIMIT_FSIZE`
  raised to 2 GiB.
- `specs/008-agent-frontend-v1/` — Demo Day frontend, currently
  on its own branch. Independent of 010 (frontend exposes the
  bug via HTTP 500 banner; the fix is agent-side).
- `specs/009-schema-context-join-graph/` — silent wrong-answer
  bugfix: extends `render_schema_block` with a join graph.
  Merged to main 2026-05-07. Independent of 010 (orthogonal
  surfaces: 009 = rendering, 010 = persistence).

The published DuckDB contract — produced by the ETL component —
remains authoritative for everything the agent reads:

- `specs/001-discogs-etl/contracts/duckdb-schema.md` — release side.
- `specs/003-masters-artists/contracts/duckdb-schema.md` — optional
  `master_fact`.

Both contracts are NULL-tolerant (release_fact.country, master_fact.year,
etc., are nullable). Their NULL-tolerance is what produces the
NaN floats that 010 sanitizes.

The agent does NOT import code from `etl/` and does NOT read
non-published artifacts. Statically enforced by
`agent/tests/unit/test_no_etl_imports.py`.

Resolved scope decisions still in force:

- **LLM provider = OpenAI** (`gpt-4o-mini` cheap, `gpt-4o` strong).
- **Multi-turn = light contextual carry-over** — only prior
  user-query *text* (capped at 4 turns / 512 tokens) flows into
  `query_understanding`.
- **Sandbox file-size budget = 2 GiB** (007 decision).
- **Schema-context join graph** (009 decision; merged).
- **JSONB input invariant** (010 decision): every dict flowing
  into a JSONB column MUST be RFC-8259-compliant. Sanitization
  happens at the persistence-write boundary via a single
  chokepoint covering all five JSONB columns.

Constitution: `.specify/memory/constitution.md` (v1.2.0). 010
does **NOT** require a constitution amendment — Principle VII.c
(read-only runtime mechanics) is the disciplinary analog; this
feature operationalizes the symmetric write-side: declare the
constraint (Postgres JSONB requires RFC-8259 JSON) and document
its consequences (NaN floats from upstream code paths must be
sanitized at the boundary). The contract amendment in
`004/contracts/postgres-schema.md §7` is the load-bearing
artifact.

The constitution prevails on any conflict.
<!-- SPECKIT END -->
