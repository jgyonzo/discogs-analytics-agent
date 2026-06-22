<!-- SPECKIT START -->
Active feature: **016-frontend-plot-layout** (branch
`016-frontend-plot-layout`) — small frontend polish spanning two
components. (US1) Rebalance the wide three-column layout in
`frontend/src/App.tsx` so the result/chart column is the widest and
the conversation is a bit narrower (keeping a usable minimum width);
mobile stacking unchanged. (US2) Legends below the plot — the chart is
opaque Plotly HTML in a sandboxed iframe, so this is an agent-side
change: a `fig.update_layout(legend=dict(orientation="h", ...))` line
added to the canonical code shape in
`agent/src/discogs_agent/prompts/code_generator.md`. (US3) Copy buttons
for the full run id and thread id badges in
`frontend/src/components/RunMetadata.tsx` (copies untruncated value,
transient "copied" state, keyboard/a11y, graceful clipboard failure).
No API/persistence/schema/DuckDB-contract changes; no new deps
(`lucide-react`, `clsx` already present); iframe sandbox unchanged.
Constitution Check passes (VI components named, VII(b) is styling not
schema prose). Plan + Phase-1 artifacts:
`specs/016-frontend-plot-layout/` (`plan.md`, `research.md`,
`data-model.md`, `quickstart.md`,
`contracts/frontend-layout.md`, `contracts/chart-legend.md`).

Prior feature: **008-agent-frontend-v1** — Demo Day frontend. A
React + Vite + TypeScript single-page app that turns the existing
agent into a demoable product: type or click a question, see a
chart inline, plus collapsible SQL, a small data preview, and
routing badges. The frontend ships as a **third** component in
this monorepo (alongside `etl/` and `agent/`), runs as a service
in the existing local docker-compose stack, and depends only on
the agent's already-shipped HTTP API plus a single CORS allowance
added to the agent. The frontend never touches DuckDB, Postgres,
ETL files, or local artifacts directly, and never executes
agent-generated Python or SQL. The chart artifact is rendered as
opaque HTML inside a sandboxed `<iframe>` (`sandbox="allow-scripts"`,
no `allow-same-origin`).

Read this feature's plan and its phase-1 artifacts:

- Plan: `specs/008-agent-frontend-v1/plan.md`
- Spec: `specs/008-agent-frontend-v1/spec.md`
- Research: `specs/008-agent-frontend-v1/research.md` (packaging,
  CORS, iframe sandbox, error mapping, state management)
- Data model: `specs/008-agent-frontend-v1/data-model.md`
  (frontend domain types + reducer state + localStorage shape)
- Contracts: `specs/008-agent-frontend-v1/contracts/`
  - `api-consumption.md` — which agent `/query` fields the frontend
    reads, ignores, or maps
  - `amendment-004-api-cors.md` — exact prose for a new §8
    "Cross-origin policy" in `004/contracts/api.md`
  - `curated-questions.md` — the V1 set of 7 demo questions and
    their spread coverage requirement
- Quickstart: `specs/008-agent-frontend-v1/quickstart.md`

Status: phases 1+2+3 (US1 MVP), phase 4 (US2 curated questions),
phase 5 (US3 multi-turn + reset), and phase 6 (US4 — SQL viewer
+ data preview + run metadata) all merged on the branch
`008-agent-frontend-v1`. Remaining: phase 7 (US5 — Docker compose
service), phase 8 (Polish). The branch was rebased over `main`
on 2026-05-07 to pull in 009's schema-context join-graph fix,
and again on 2026-05-08 to pull in 010's JSONB NaN sanitization
fix.

In-flight follow-on (current): **`015-classifier-carryover`**
(branch `015-classifier-carryover`) — agent-side hardening
triggered by thread `9214f7fb-...` on 2026-05-11, where two
short follow-up questions ("and what is the second one?" and
"and the top 5?") were rejected as `clarification_needed`
because the classifier (router) sees only `{user_query}` +
`{schema_context_block}` — it doesn't receive the multi-turn
carryover preamble that the next node (`query_understanding`)
already consumes. Structural wiring bug: carryover is built and
consumed in `query_understanding`, AFTER the classifier
short-circuits to clarification_needed. Two work items: (US1)
extract `_load_carryover` from `query_understanding.py` to
`_carryover.py` as a public helper; call it in the router
BEFORE invoking `query_classifier`; populate state; pass
`carryover_preamble` into `ClassifierInput`; add
`{carryover_block}` placeholder + follow-up-resolution
instructions to `router.md`. (US2) Persist carryover at
run-start (falls out of US1's earlier state population) so
`metadata_json.carryover` is no longer `null` on 2nd+-turn
clarification_needed runs — operators can see what context
the classifier had. Plus an admin task: 013's pointer
`successor-015-pointer.md` is renumbered to
`successor-016-pointer.md` because 015 is now this spec
(second renumbering of the same pointer; 014 already did
014→015). See
`specs/015-classifier-carryover/plan.md`.

Prior 004-family work (still authoritative):

- `specs/004-agent-v1/` — V1 baseline (graph, API, sandbox, SQL
  safety, generated-code shape, persistence). The frontend's
  consumption shape is anchored against `004/contracts/api.md`.
  010 amended `004/contracts/postgres-schema.md` with the new §7
  JSONB input invariant.
- `specs/005-agent-schema-context/` — schema enrichment + sample
  values + glossary + the `succeeded_empty` zero-row guardrail.
  Amended by 009 with a new "Join graph" section.
- `specs/006-bugfix-postmortem/` — three-bug postmortem and
  Constitution v1.2.0 amendment (Principle VII: Implementation
  Discipline). 009 and 010 are both VII follow-throughs (009 =
  VII.b prompt-authoring; 010 = VII.c-analog write-side).
- `specs/007-sandbox-fsize-budget/` — sandbox `RLIMIT_FSIZE`
  raised to 2 GiB; `004/contracts/code-generation.md §3.1.1`
  amended.
- `specs/009-schema-context-join-graph/` — silent wrong-answer
  bugfix: extends `render_schema_block` with a join-graph section
  delivering FK relationships, cross-grain traversal hints, and
  forbidden-join anti-patterns. Closes the
  `master_fact.master_id = release_artist_bridge.release_id`
  class of LLM hallucination. Merged to main 2026-05-07.
- `specs/010-jsonb-nan-sanitization/` — silent persistence-500
  bugfix: SQLAlchemy `TypeDecorator` chokepoint sanitizes
  NaN/Infinity floats out of every JSONB column write before
  Postgres rejects them. Closes any agent run whose dataframe
  preview legitimately contains NULL cells. Merged to main
  2026-05-08.
- `specs/012-catalog-aggregation-postmortem/` — SDD back-fill of
  three hotfixes against catalog-wide OOM-kills:
  `memory_limit=1GB` in generated DuckDB connect-config, tmpfs
  bumped to 6 GiB, and glossary entry #3 first-round rewrite
  steering the LLM away from `release_unique_view` for catalog-
  wide aggregations.
- `specs/013-filtered-aggregation-postmortem/` — follow-on
  to 012. Observability fix (`oom_killed` named exception_type
  for external SIGKILL) + glossary entry #3 second-round
  rewrite (drops the "catalog-wide" qualifier; blanket ban on
  view-in-JOIN/GROUP-BY regardless of WHERE filters). Triggered
  by the Depeche Mode failure run (`b809ca52-...`). Merged to
  main 2026-05-11.
- `specs/014-cross-grain-join-postmortem/` — follow-on to 013
  + 009. Resolves the contradiction 013 introduced between
  009's cross-grain traversal hint and 013's glossary
  tightening; updates the hint to recommend `release_fact`
  instead of `release_unique_view`; promotes the forbidden-
  joins list to static enforcement in `sql_safety_checker`
  (`rule="forbidden_join"`). Triggered by run `2557c2ce-...`
  on 2026-05-10. Merged to main 2026-05-11.

The published DuckDB contract — produced by the ETL component —
remains authoritative for everything the agent reads:

- `specs/001-discogs-etl/contracts/duckdb-schema.md` — release side
  (`release_fact`, `release_unique_view`, `release_artist_bridge`,
  `release_label_bridge`).
- `specs/003-masters-artists/contracts/duckdb-schema.md` — optional
  `master_fact`. The "Counting / joining rules" section of this
  contract is the source of truth for the join graph 009 renders
  into the LLM-facing schema-context block. Both contracts are
  NULL-tolerant (release_fact.country, master_fact.year, etc.,
  are nullable) — that NULL-tolerance is what produces the NaN
  floats that 010 sanitizes at the persistence boundary.

The agent does NOT import code from `etl/` and does NOT read
non-published artifacts. Statically enforced by
`agent/tests/unit/test_no_etl_imports.py`. The frontend does NOT
import code from either `etl/` or `agent/`, and physically cannot
read `data/` because it never has the volume mounted.

Resolved scope decisions still in force:

- **LLM provider = OpenAI** (`gpt-4o-mini` cheap, `gpt-4o` strong).
- **Multi-turn = light contextual carry-over** — only prior
  user-query *text* (capped at 4 turns / 512 tokens) flows into
  `query_understanding`. No prior SQL/code carry-over.
- **Sandbox file-size budget = 2 GiB** (007 decision).
- **Schema-context join graph** (009 decision; merged to main).
  The rendered block delivers FK edges + cross-grain traversal
  hints + forbidden-join anti-patterns. The 005 contract is
  amended to make the section normative.
- **JSONB input invariant** (010 decision; merged to main). Every
  dict flowing into a JSONB column MUST be RFC-8259-compliant.
  Sanitization happens at the persistence-write boundary via a
  single chokepoint (`_SanitizedJSON` `TypeDecorator` in
  `agent/src/discogs_agent/persistence/models.py`) covering all
  five JSONB columns. The 004 contract gains §7 making this
  invariant normative.
- **Frontend stack = React 18 + Vite + TypeScript + Tailwind**
  (008 decision; matches the source brief at
  `docs/discogs_frontend_initial_spec.md`).
- **Frontend packaging = Vite dev-server in container** for V1
  (008 decision; nginx-served static build deferred to V1.1).
- **CORS allowlist** = settings-sourced env var
  `CORS_ALLOWED_ORIGINS`, defaulting to
  `["http://localhost:5173", "http://localhost:3000"]`,
  `allow_credentials = False`.

Constitution: `.specify/memory/constitution.md` (v1.2.0). 008 does
**NOT** require a constitution amendment to begin. The plan does
recommend a follow-up **PATCH** amendment (Principle VI's prose
"two independently deployable components" → "two or more") to be
landed after 008 merges; the operational rules of Principle VI
already accommodate a third component. See plan §"Constitution
amendment recommendation".

The constitution prevails on any conflict.
<!-- SPECKIT END -->
