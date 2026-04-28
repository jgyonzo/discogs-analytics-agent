<!-- SPECKIT START -->
Active feature: **003-masters-artists** (Fase 4 — masters analytics
+ artists pipeline foundation). For the active scope, technical
context, contracts deltas, and verification walkthrough, read this
feature's plan and its phase 1 artifacts:

- Plan: `specs/003-masters-artists/plan.md`
- Spec: `specs/003-masters-artists/spec.md`
- Research (implementation decisions for Fase 4):
  `specs/003-masters-artists/research.md`
- Data model (new schemas + master_fact build contract):
  `specs/003-masters-artists/data-model.md`
- Contracts: `specs/003-masters-artists/contracts/`
  (`cli.md`, `duckdb-schema.md`, `manifest.md` — all deltas vs
  Fase 1 / 2+3)
- Quickstart: `specs/003-masters-artists/quickstart.md`

Earlier-phase artifacts remain authoritative for everything not
diffed by this spec:
- `specs/001-discogs-etl/contracts/duckdb-schema.md` —
  authoritative for the unchanged release-side tables and the
  `release_unique_view` view (Fase 4 adds `master_fact` as a new
  table; existing tables are byte-stable).
- `specs/001-discogs-etl/contracts/manifest.md` and
  `specs/002-etl-scaleup/contracts/manifest.md` — authoritative
  for the manifest top-level shape and the `step_metrics` block;
  Fase 4 adds new `source_files` keys, `step_durations` /
  `step_metrics` entries, and well-known warning names.
- `specs/002-etl-scaleup/data-model.md` — authoritative for the
  DQ-dispatch threshold pattern; Fase 4 reuses it.

Constitution: `.specify/memory/constitution.md` (v1.1.0).
Fase 4 uses the constitution's "explicit scope decision recorded
in the relevant feature spec" escape hatch
(Technical Constraints / Scope guardrails) to expand beyond the
v1-only-non-goals language. **No constitution amendment required.**

The constitution prevails on any conflict.
<!-- SPECKIT END -->
