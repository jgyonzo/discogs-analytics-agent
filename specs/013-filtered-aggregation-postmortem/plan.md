# Implementation Plan: Filtered-aggregation postmortem — sandbox OOM observability + glossary follow-on

**Branch**: `013-filtered-aggregation-postmortem` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Forward implementation following the Depeche Mode incident (run `b809ca52-12bc-4268-99d4-7603a5d0ecdd`) that slipped past 012's catalog-wide framing.

## Summary

Forward implementation, two work streams:

1. **Observability (US1)** — Make sandbox SIGKILL events first-class observable. Today the catch-all branch in `sandbox/runner.py` labels any non-timeout SIGKILL as `"nonzero_exit"`, which is indistinguishable from any other unknown failure. After 013, `exit_code < 0` outside the harness's own timeout path produces `exception_type = "oom_killed"` (for `-9`) or `"sandbox_signaled"` (for other negatives). `chart_validator` translates `"oom_killed"` into a single named rule; the response synthesizer emits a memory-pressure hint; the repair prompt sees the named cause.

2. **Glossary tightening (US2)** — Drop the "catalog-wide aggregations" qualifier from glossary entry #3. The new wording forbids `release_unique_view` in any JOIN or GROUP BY regardless of WHERE filters, and explicitly carves out only `WHERE release_id = <literal>` spot-checks. Mirrored across the three surfaces (renderer, `code_generator.md`, `repair_code.md`) and locked by regenerating the integration-test golden.

Plus three documentation cleanups: (a) Q1's stale description in `008/contracts/curated-questions.md`, (b) a new sandbox-exception-taxonomy contract that pins the allowed `exception_type` values, (c) a pointer to a future ETL-component spec (provisional `014-release-unique-view-materialization`) that would rewrite the view's materialization and earn the abstraction its keep.

## Technical Context

**Language/Version**: Python 3.12 (existing agent runtime).
**Primary Dependencies**: existing — `duckdb`, `subprocess` stdlib, `pydantic-settings`, `pytest`. No new dependencies.
**Storage**: published DuckDB (`:ro` mount) and Postgres for run records. Schema changes: none (the new exception_type values flow through the existing `agent_tool_calls.output_json` JSON column).
**Testing**: pytest. New tests needed for the runner signal-mapping branch and the validator named-rule branch; existing schema-context golden regenerated.
**Target Platform**: Linux container (production), macOS host (dev). Signal-mapping behavior is platform-portable: POSIX `subprocess.Popen.returncode < 0` means "killed by signal `-returncode`" on Linux and macOS alike.
**Project Type**: agent component only (Constitution Principle VI). Touches:

- `agent/src/discogs_agent/sandbox/runner.py` (FR-001 signal-aware exception_type).
- `agent/src/discogs_agent/tools/chart_validator.py` (FR-002 named rule translation).
- `agent/src/discogs_agent/duckdb_layer/schema.py` (FR-006 glossary entry #3).
- `agent/src/discogs_agent/prompts/code_generator.md` (FR-008 Critical rule).
- `agent/src/discogs_agent/prompts/repair_code.md` (FR-009 reminder + FR-004 cause plumbing).
- `agent/src/discogs_agent/graph/nodes/response_synthesizer.py` or equivalent message assembler (FR-003 OOM-aware copy).
- `agent/tests/integration/golden/schema_context_block.txt` (FR-010 regenerated golden).
- `specs/008-agent-frontend-v1/contracts/curated-questions.md` line 18 (FR-011 Q1 description).
- `specs/004-agent-v1/contracts/code-generation.md` §3.4 (FR-013 amendment).
- `specs/005-agent-schema-context/contracts/schema-context.md` glossary entry #3 (FR-012 amendment).
- 013's own `contracts/sandbox-exception-taxonomy.md` (FR-014 new contract).
- 013's own `contracts/successor-014-pointer.md` (FR-015 future-spec pointer).

**Performance Goals**: no perf budget change. The signal-mapping branch is O(1) string assignment. The glossary tightening is a wording change. SC-002 ("Depeche Mode question succeeds post-013") relies on the LLM picking a cheaper plan once the loophole is closed; the cheaper plan was always available — only the prompt steering changes.

**Constraints**:
- The new exception_type taxonomy MUST be deterministic and side-effect-free (FR-005).
- Constitution VII.a (Configuration sources): the new string literals (`"oom_killed"`, `"sandbox_signaled"`) are taxonomy constants, not configuration; they live in code, not env vars. Same status as the pre-existing `"timeout"` / `"nonzero_exit"` / `"no_result"` literals.
- Constitution VII.b (Prompt-authoring): glossary text lives in the dynamically-rendered `{schema_context_block}`; mirrored prompt text is rules-of-thumb (carve-out).
- Constitution VII.c (Read-only runtime): 013 is the symmetric *observability* analog — declares the existing read-only runtime constraint's *failure consequence* (OOM-kill is reachable, here is what it looks like, here is the named cause).

**Scale/Scope**: ~6 files changed in `agent/`, ~4 documentation files written or updated. ~1 hour of implementation work, ~2 hours of tests + golden regeneration + manual replay.

## Constitution Check

| Principle | Engaged? | Verdict |
|-----------|----------|---------|
| I — Layered, Contract-First Data Architecture | No | No published-DuckDB schema change. The view's pathological definition is acknowledged but not fixed in 013; FR-015 documents the deferral. |
| II — Streaming, Bounded-Memory Processing | Indirectly | 013 doesn't change the budget; it makes a budget-breach observable when one happens. The principle's *intent* (bounded resources) is preserved. ✅ |
| III — Reproducible Runs | Indirectly | The new exception_type values appear in `agent_tool_calls.output_json` and are deterministic per FR-005. Re-running the same failed input produces the same labeled cause. ✅ |
| IV — Data Quality Gates | No | Not engaged. No new DQ checks. |
| V — Agent-Friendly Analytics Surface | Yes — *nuance* | Principle V explicitly names `release_unique_view` on the agent-facing surface and states "Counts of unique releases MUST be expressible via `COUNT(DISTINCT release_id)` or `release_unique_view`". After 013, `COUNT(DISTINCT release_id)` remains the canonical path; the view remains *on the surface* (so the principle's surface-stability commitment is honored) but the agent is steered away from it for everything except spot-checks. The view becomes a degraded part of the surface, not removed from it — same status it had post-012, just tightened. No surface-removal, no violation. The nuance is recorded in FR-015's pointer to the future ETL fix that would restore the view's full utility. ✅ |
| VI — Two Components, One Contract | Yes | Fully inside `agent/`. Zero edits to `etl/` or `frontend/`. The 008 documentation edit (FR-011) is a description-line fix in a spec doc, not a frontend code change. ✅ |
| VII.a — Configuration sources | Yes — *trade-off* | The new exception_type string literals (`"oom_killed"`, `"sandbox_signaled"`) are hardcoded in `sandbox/runner.py`. **Trade-off**: making them env-driven would invite operator-introduced drift between code and dashboards. The literals are a *taxonomy*, not a configuration choice — same status as the existing `"timeout"` / `"no_result"` literals. The exact-string-match contract is documented in 013/contracts/sandbox-exception-taxonomy.md (FR-014). ✅ |
| VII.b — Prompt-authoring discipline | Yes — load-bearing | The glossary tightening (FR-006) ships through `_DOMAIN_GLOSSARY`, which renders into the dynamic `{schema_context_block}`. The mirrored "Critical rule" in `code_generator.md` (FR-008) and the reminder in `repair_code.md` (FR-009) are rules-of-thumb tied to the prompts' roles (VII.b's carve-out), not catalog descriptions. The repair-prompt context that carries the new exception_type (FR-004) is dynamic per-run state, not static schema prose. Same status as 012, extended one notch. ✅ |
| VII.c — Read-only runtime mechanics | Yes — analog | 013 is the symmetric *observability* analog of VII.c. It declares the runtime constraint's failure consequence (the cgroup memory cap *is* reachable from inside; here is how that surfaces) alongside the constraint, rather than leaving the next operator to rediscover it from `exit_code=-9` and an empty stderr. The 004 amendment §3.4 (FR-013) is the load-bearing artifact. ✅ |

**Gate result**: PASS. The plan respects Principles I–VII without exception. Two trade-offs (V's surface-nuance, VII.a's taxonomy literals) are surfaced rather than smuggled.

**Component(s) touched**: `agent/` only.

## Project Structure

### Documentation (this feature)

```text
specs/013-filtered-aggregation-postmortem/
├── spec.md                                              # Already written
├── plan.md                                              # This file
├── research.md                                          # Phase 0 — taxonomy + wording decisions
├── data-model.md                                        # Phase 1 — minimal (taxonomic entities only)
├── contracts/
│   ├── amendment-004-code-generation.md                 # §3.4 failure-modes table + new §3.4.x for oom_killed
│   ├── amendment-005-schema-context.md                  # Glossary entry #3 rewrite (second round)
│   ├── sandbox-exception-taxonomy.md                    # Canonical set of exception_type values
│   └── successor-014-pointer.md                         # Future ETL-component follow-on pointer
├── checklists/
│   └── requirements.md                                  # Already written; all items pass
├── quickstart.md                                        # Phase 1 — verification script (replay Depeche Mode)
└── tasks.md                                             # Phase 2 — `/speckit-tasks` output (NOT created here)
```

### Source Code (this feature — to-be-changed)

```text
agent/src/discogs_agent/sandbox/runner.py                       # FR-001 signal-aware exception_type
agent/src/discogs_agent/tools/chart_validator.py                # FR-002 named rule translation
agent/src/discogs_agent/duckdb_layer/schema.py                  # FR-006 _DOMAIN_GLOSSARY entry #3
agent/src/discogs_agent/prompts/code_generator.md               # FR-008 Critical rule (lines 6–17)
agent/src/discogs_agent/prompts/repair_code.md                  # FR-009 reminder + FR-004 context plumbing
agent/src/discogs_agent/graph/nodes/response_synthesizer.py     # FR-003 OOM-aware final message (exact path tbc in research.md)
agent/tests/integration/golden/schema_context_block.txt         # FR-010 regenerated golden

agent/tests/unit/test_sandbox_signal_mapping.py                 # NEW — exercises FR-001 (-9 → "oom_killed"; other negatives → "sandbox_signaled")
agent/tests/unit/test_chart_validator_oom_rule.py               # NEW — exercises FR-002

specs/008-agent-frontend-v1/contracts/curated-questions.md      # FR-011 Q1 description line (line 18)
```

**Structure Decision**: agent-component-only forward implementation. Doc surface mirrors 012's layout exactly (4 contracts under `contracts/`, one of which is a future-spec pointer rather than an amendment to an existing contract — 012 didn't have that shape, but it fits VII's "name the deferred work" intent). New `tests/unit/` modules are the load-bearing additions on the code side; the rest are edits to existing files.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Nothing to track. Constitution Check passed with no violations. The two nuances surfaced (Principle V's surface-narrowing, VII.a's taxonomy literals) are documented inline in the table and are not violations — they are honest trade-offs within the principles' carve-outs.
