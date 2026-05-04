# Implementation Plan: Agent Schema Context Enrichment

**Branch**: `005-agent-schema-context` | **Date**: 2026-05-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-agent-schema-context/spec.md`

## Summary

Enrich the schema-context payload the agent passes to its LLM
prompts so the model can distinguish *coarse* `primary_genre`
buckets (Rock, Electronic, ...) from *granular* `style` values
(Techno, House, ...). Add a small one-line domain glossary and
a "trend-over-time → prefer `decade`" hint. Add a zero-row
guardrail in the chart-validation phase so the agent surfaces
*"no matching releases"* with the SQL used, rather than
publishing a blank chart artifact and reporting `succeeded`.

The fix is **agent-only** (Component B). The published DuckDB
contract (`specs/001-discogs-etl/contracts/duckdb-schema.md`)
is untouched. The graph topology, retry policy, and tool
allowlist from `004-agent-v1` are preserved; the only Postgres
change is one additive migration to extend the `agent_runs`
status CHECK constraint with a new `succeeded_empty` value.

## Technical Context

**Language/Version**: Python 3.12 (matches `004-agent-v1` and
the agent venv at `agent/.venv/`).
**Primary Dependencies**: LangGraph (graph), LangChain-OpenAI
(LLM), DuckDB (read-only analytics), FastAPI (HTTP),
SQLAlchemy + Alembic (Postgres persistence). All already
present.
**Storage**: Postgres 16 (agent state, traces); DuckDB (read
the published catalog). Both already configured.
**Testing**: pytest (`agent/tests/unit`, `tests/integration`,
`tests/golden`). The existing 45-test suite is the floor.
**Target Platform**: containerised on AWS (per Principle VI);
local Docker Compose for dev (`agent-api-1` from the README).
**Project Type**: web service (Component B per Principle VI).
**Performance Goals**: schema-context build at startup must
finish in under 5 s on the full-dump DuckDB; per-request
overhead from the enriched context stays under 600 tokens.
**Constraints**: no published-DuckDB-contract change (Principle
I + VI); no relaxation of two-pass SQL safety or sandbox
restrictions (`004-agent-v1/contracts/sql-safety.md` and
`code-generation.md`); no cross-component imports.
**Scale/Scope**: published catalog has ~22M release rows, ~14
distinct `primary_genre` values, ~600 distinct `style` values,
and ~250 distinct `country` values; sampling will produce
small bounded blocks regardless of catalog growth.

## Constitution Check

Component(s) touched: **agent only** (Component B). No ETL or
published-DuckDB change.

| Principle | Engaged? | How this plan complies |
|-----------|----------|------------------------|
| I. Layered, Contract-First Data Architecture | ✅ | The published-DuckDB contract is unchanged. The enriched schema-context is an internal agent artifact; it READS the same documented columns (`primary_genre`, `style`, `decade`, `country`). |
| II. Streaming, Bounded-Memory Processing | n/a | Agent-side only; no XML/Parquet processing. Sample-value queries are bounded `LIMIT N` SELECTs. |
| III. Reproducible Runs with Manifest & Logs | ✅ | The cache key for the schema context includes the published DuckDB's `run_id` from `release_unique_view` so a republished catalog invalidates the cache. Existing `agent_run_log` / `agent_node_log` rows continue to record the run. |
| IV. Data Quality Gates | ✅ | Zero-row results, previously silent, now produce a distinct terminal state with the SQL preserved — a quality gate at the consumer layer. |
| V. Agent-Friendly Analytics Surface | ✅ | The fix REINFORCES Principle V by surfacing the `primary_genre` vs `style` distinction the surface already encodes — closing a gap that let the agent miscount/empty-count. No new analytics tables; no new columns; no row-multiplication risk introduced. |
| VI. Two Components, One Contract | ✅ | All changes live under `agent/`. No imports from `etl/`, no reads of non-published artifacts, no DuckDB schema modification. The published-DuckDB remains the only contact surface. |

**Gate result**: PASS. No Complexity Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/005-agent-schema-context/
├── plan.md                 # This file
├── spec.md                 # Specification (already written)
├── research.md             # Phase 0 output (this command)
├── data-model.md           # Phase 1 output (this command)
├── quickstart.md           # Phase 1 output (this command)
├── contracts/              # Phase 1 output (this command)
│   ├── schema-context.md   # Shape of the enriched payload
│   └── empty-result.md     # New terminal status + sandbox handling
├── checklists/
│   └── requirements.md     # Spec quality checklist (already written)
└── tasks.md                # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
agent/
├── src/discogs_agent/
│   ├── duckdb_layer/
│   │   ├── schema.py            # EXTENDED: SchemaContext gains a sampled-values block + domain glossary
│   │   └── allowlist.py         # unchanged
│   ├── prompts/
│   │   ├── router.md            # EDITED: render new {sample_values_block} + glossary
│   │   ├── query_understanding.md # EDITED: same; surface decade-preference
│   │   ├── code_generator.md    # EDITED: same
│   │   └── repair_code.md       # EDITED: same
│   ├── graph/
│   │   ├── state.py             # unchanged shape; no new fields required
│   │   └── nodes/
│   │       └── chart_validator.py # EXTENDED: detect row_count==0 → terminal_status=succeeded_empty
│   ├── tools/
│   │   └── chart_validator.py   # EXTENDED: emit a new validator outcome reason
│   └── persistence/
│       └── migrations/versions/
│           └── 005_xx_add_succeeded_empty.py  # NEW: extend agent_runs status CHECK
└── tests/
    ├── unit/
    │   ├── test_schema_context.py     # EXTENDED: assert sample block + glossary present, size bounded
    │   ├── test_chart_validator.py    # EXTENDED: zero-row case maps to succeeded_empty
    │   └── test_query_classifier.py   # EXTENDED: with sample block, "Techno" routes to simple, not unsupported
    ├── integration/
    │   └── test_schema_context_real_duckdb.py  # NEW: connects to a small fixture DuckDB
    └── golden/
        └── test_canonical_styles.py    # NEW: 10 canonical style queries → assert non-empty results
```

**Structure Decision**: Stay within the existing `agent/`
component layout. No new top-level directories. The
schema-context enrichment is a pure extension of
`duckdb_layer/schema.py` and four prompt files; the zero-row
guardrail is an extension of the existing `chart_validator`
node and tool. The Postgres schema gets one additive Alembic
migration. No new graph nodes, no new edges.

## Complexity Tracking

> No Constitution Check violations. This section is intentionally
> empty. The new `succeeded_empty` terminal state is documented
> in `contracts/empty-result.md` and reflected in the additive
> Alembic migration; both are within Principle V's "deliberate
> additions are allowed" envelope.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none)    | (n/a)      | (n/a)                                |
