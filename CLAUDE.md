<!-- SPECKIT START -->
Active feature: **005-agent-schema-context** — bug-fix &
enrichment for the V1 agent (`004-agent-v1`). The agent's
prompts received column NAMES only; the LLM had no way to know
that "Techno" is a `style` value, not a `primary_genre` value,
so style queries silently returned zero rows and rendered
blank charts. This feature enriches the schema-context payload
with sample values + a domain glossary, adds a "trend → prefer
decade" hint, and adds a zero-row guardrail (`succeeded_empty`)
so empty results surface as a clear "no matching releases"
reply instead of a blank chart with `status: succeeded`.

Read this feature's plan and its phase-1 artifacts:

- Plan: `specs/005-agent-schema-context/plan.md`
- Spec: `specs/005-agent-schema-context/spec.md`
- Research: `specs/005-agent-schema-context/research.md`
- Data model: `specs/005-agent-schema-context/data-model.md`
- Contracts: `specs/005-agent-schema-context/contracts/`
  - `schema-context.md` — enriched payload shape + token budget
  - `empty-result.md` — `succeeded_empty` status + chart_validator wiring
- Quickstart: `specs/005-agent-schema-context/quickstart.md`

Prior agent spec (still authoritative for graph, API, sandbox,
SQL safety, generated-code shape):

- `specs/004-agent-v1/plan.md` and its `contracts/` (api.md,
  graph.md, tools.md, sql-safety.md, code-generation.md,
  postgres-schema.md). 005 is an additive overlay on 004.

The published DuckDB contract — produced by the ETL component
— remains authoritative for everything the agent reads:
- `specs/001-discogs-etl/contracts/duckdb-schema.md` — release
  side (`release_fact`, `release_unique_view`, `release_artist_bridge`,
  `release_label_bridge`).
- `specs/003-masters-artists/contracts/duckdb-schema.md` —
  optional `master_fact`.

The agent does NOT import code from `etl/` and does NOT read
non-published artifacts (no `stg_*`, no `clean_*`, no raw XML,
no Parquet at query time). This is enforced statically by
`agent/tests/unit/test_no_etl_imports.py` and physically by
mounting only the published DuckDB into the agent container.

Two scope decisions resolved during /speckit-specify:
- **LLM provider = OpenAI** (`gpt-4o-mini` cheap,
  `gpt-4o` strong). Provider-agnostic abstraction is future
  work.
- **Multi-turn = light contextual carry-over** — only prior
  user-query *text* (capped at 4 turns / 512 tokens) flows into
  `query_understanding`. No prior SQL/code carry-over.

Constitution: `.specify/memory/constitution.md` (v1.1.0).
Constitution v1.1.0 already defers the agent's framework, model
choice, and sandboxing strategy to "the agent's own initial
spec" (Technical Constraints / Components & runtime targets) —
which is exactly this spec. **No constitution amendment
required.**

The constitution prevails on any conflict.
<!-- SPECKIT END -->
