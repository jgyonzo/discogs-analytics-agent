# Implementation Plan: Sandbox file-size budget

**Branch**: `007-sandbox-fsize-budget` | **Date**: 2026-05-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-sandbox-fsize-budget/spec.md`

## Summary

Raise `RLIMIT_FSIZE_BYTES` in the sandbox subprocess from **64 MiB**
(sized for a Plotly inline-JS HTML alone) to **2 GiB** (sized for a
release-grain `GROUP BY` spill against the ~17M-release published
catalog). Amend `004/contracts/code-generation.md §3.1` to document
that `RLIMIT_FSIZE` is process-wide and shared between the chart
artifact and DuckDB spill files; capture the workload-sizing
rationale and the named past incident (the failing
*"show the number of releases over time"* query).

Add one regression test under `agent/tests/integration/` that fails
on the old 64 MiB cap and passes on the new 2 GiB cap, by running a
synthetic aggregation against a fixture sized to overflow the old
cap. No other sandbox restriction changes.

## Technical Context

**Language/Version**: Python 3.12 (existing agent runtime).
**Primary Dependencies**: existing — `duckdb`, `pandas`, `pytest`.
No new dependencies.
**Storage**: published DuckDB (`:ro` mount), tmpfs at `/tmp/duckdb`
(host-default size ≈ half of RAM).
**Testing**: pytest (existing fixtures: `seed_duckdb`, `agent_env`,
`tmp_artifact_dir`). One new fixture: a "spill-forcing" DuckDB
roughly the size needed to overflow the pre-fix 64 MiB cap.
**Target Platform**: Linux container (production), macOS host (dev).
RLIMIT_FSIZE semantics are identical on both — Linux returns EFBIG;
macOS returns EFBIG via the same `setrlimit(RLIMIT_FSIZE, …)` path.
**Project Type**: agent component only (Constitution Principle VI).
Zero edits to `etl/`. Touches:

- `agent/src/discogs_agent/sandbox/restrictions.py` (one constant +
  the surrounding rationale comment)
- `specs/004-agent-v1/contracts/code-generation.md` (§3.1 amendment)
- `agent/tests/integration/test_sandbox_fsize_budget.py` (new)
- optional: `agent/tests/fixtures/spill_seed.py` (new generator)

**Performance Goals**: full-catalog `GROUP BY decade COUNT(DISTINCT
release_id)` against `release_unique_view` succeeds end-to-end with
no `IO Error: File too large`; existing seed-fixture tests
unaffected.
**Constraints**: `RLIMIT_FSIZE` is process-wide on Linux — single
ceiling shared between chart HTML and DuckDB spill (cannot be split
under the V1 in-process subprocess sandbox). The cwd-jail
(per-run artifact dir) remains the **primary** write-confinement
control; RLIMIT_FSIZE is the **secondary** runaway-write backstop.
**Scale/Scope**: one Python constant change, one contract clause,
one regression test, one optional fixture-generator. No public API
changes, no DuckDB schema changes, no new env vars.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Engaged? | Verdict |
|-----------|----------|---------|
| I — Layered, Contract-First Data Architecture | No | No published-DuckDB schema change. Agent-only fix. |
| II — Streaming, Bounded-Memory Processing | Indirectly | The bug is *exactly* an unbounded-spill failure under a too-small write cap. The fix lets DuckDB do its bounded streaming spill within the sandbox, restoring the principle's intent at the agent layer. ✅ |
| III — Reproducible Runs | No | Not engaged — agent-side. |
| IV — Data Quality Gates | No | Not engaged. |
| V — Agent-Friendly Analytics Surface | No | No new tables/columns/views. |
| VI — Two Components, One Contract | Yes | The fix is fully inside `agent/`. No ETL imports introduced. The published DuckDB is still consumed `:ro` and unmodified (SC-005 anchor). ✅ |
| VII.a — Configuration sources | Considered | The cap stays a Python module-level constant, **not** an env var. RLIMIT_FSIZE is a security-critical sandbox invariant; making it operator-tunable would let a misconfiguration silently weaken the secondary write backstop. The contract amendment documents the rationale. ✅ |
| VII.b — Prompt-authoring discipline | No | No prompt changes. |
| VII.c — Read-only runtime mechanics | Yes | This *is* the next layer of the same family of issues 006 fixed — the published DuckDB is `:ro` → DuckDB needs to spill → the previous fix moved the spill *path* off the `:ro` mount, this fix sizes the *cap* on those spill files. The contract amendment fulfills VII.c's "document the constraint's *consequences* alongside it" by making the chart-vs-spill RLIMIT_FSIZE conflation explicit and citing the named incident. ✅ |

**Gate result**: PASS. No violations to record.

**Component(s) touched**: `agent/` only. Zero edits to `etl/`.

## Project Structure

### Documentation (this feature)

```text
specs/007-sandbox-fsize-budget/
├── plan.md                                   # This file
├── research.md                               # Phase 0 output (workload sizing)
├── contracts/
│   └── amendment-004-code-generation.md      # The actual diff to land in 004's contract
├── quickstart.md                             # Manual repro + regression-test invocation
└── tasks.md                                  # Phase 2 output (/speckit-tasks)
```

No `data-model.md`: this feature introduces no entities. No new
agent contract (`api.md`, `graph.md`, `tools.md`, …) is created;
the existing `004/contracts/code-generation.md` is *amended*, and
the amendment text is staged in `contracts/amendment-004-code-generation.md`
for review before it lands in 004.

### Source Code (repository root)

```text
agent/
├── src/discogs_agent/sandbox/
│   └── restrictions.py                       # one-constant change + rationale comment
├── tests/integration/
│   └── test_sandbox_fsize_budget.py          # NEW — fails at 64 MiB, passes at 2 GiB
└── tests/fixtures/
    └── spill_seed.py                         # NEW (optional) — synthetic spill-forcing DuckDB
```

`specs/004-agent-v1/contracts/code-generation.md` is amended in the
same change set — that file lives outside `agent/` but it is the
contract this feature is updating.

**Structure Decision**: agent-only patch + 004-contract amendment.
The constitution amendment is **not** required (per Spec §
Assumptions and the VII.c gate analysis above).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

(Not applicable — no constitution violations.)

## Phase 0 — Research

Single research question: **what is the right byte-count for
`RLIMIT_FSIZE_BYTES`?** The decision plus its rationale is captured
in [`research.md`](./research.md) and re-stated below for the
Constitution Check trail.

**Decision**: `RLIMIT_FSIZE_BYTES = 2 * 1024 * 1024 * 1024` (2 GiB).

**Rationale** (full reasoning in `research.md`):

- Workload upper bound: a release-grain `GROUP BY` against the
  full April-2026 catalog (~17M unique releases × 8 bytes per
  BIGINT release_id × ~2x hash-table overhead × ~14 decade
  buckets if worst-case partitioned) yields ~500 MB - 1 GB of
  intermediate state. DuckDB's columnar-compressed spill format
  is typically smaller than the in-memory representation, so a
  single spill file landing at ≤ 1 GiB is realistic.
- 2 GiB gives 2-4× headroom above the canonical reproducer
  without being so large it loses its disk-exhaustion-backstop
  meaning.
- 2 GiB is comfortably below the host tmpfs default (≈ 8 GiB on
  a 16 GB laptop) and below typical container memory caps (4-8
  GiB), so the cap will trigger before tmpfs `ENOSPC` does —
  giving us a single, predictable failure mode for over-spill
  cases.
- Plotly inline-JS HTML for any realistic chart is well under
  the cap (the worst observed in `agent/tests/` is ≈ 4 MB), so
  raising the cap does not shift any chart-artifact concern.

**Alternatives considered** (full table in `research.md`):

- 1 GiB — risks tripping on legitimate full-catalog
  aggregations during a brief peak-spill moment.
- 4 GiB — wastes the disk-exhaustion-backstop margin without
  unlocking any realistic V1 query.
- 8 GiB — only sensible on production VMs with ≥ 32 GB RAM;
  premature for V1.
- Move the cap into an env var (`SANDBOX_FSIZE_LIMIT_BYTES`).
  Rejected on Constitution VII.a grounds: a security-critical
  sandbox invariant is not an operator-tunable knob.
- Drop RLIMIT_FSIZE entirely and rely on the cwd jail + tmpfs
  size. Rejected: the cwd jail does not bound writes *inside*
  the per-run artifact directory; without RLIMIT_FSIZE, a
  generated chart could fill the bind-mounted `./artifacts/`
  on the host.

**Output**: `research.md` (the long-form decision), this Summary
section's recap, and the contract amendment in `contracts/`.

## Phase 1 — Design & Contracts

**Prerequisites**: `research.md` complete (decision = 2 GiB).

1. **Entities** — none. Skip `data-model.md`.

2. **Contracts** — single artifact:
   `contracts/amendment-004-code-generation.md`. It carries the
   exact prose to land in `specs/004-agent-v1/contracts/code-generation.md
   §3.1` (the sandbox restrictions table + accompanying paragraph),
   including:
   - The new constant value (2 GiB) with the rationale paragraph.
   - The explicit caveat that `RLIMIT_FSIZE` is process-wide on
     Linux, so this single ceiling caps both the chart artifact
     and DuckDB spill files (consequence of the V1 in-process
     subprocess sandbox model).
   - A "primary vs. secondary control" note: cwd jail = primary;
     RLIMIT_FSIZE = secondary backstop.
   - A named-incident citation linking back to this spec
     (`007-sandbox-fsize-budget`) and the failing query.

3. **Quickstart** — `quickstart.md`. Walks the reviewer through:
   - The manual reproducer against the published DuckDB (the
     query the user actually ran).
   - The regression-test invocation (`pytest
     tests/integration/test_sandbox_fsize_budget.py`).
   - How to verify the new cap is in force (e.g.
     `python -c "from discogs_agent.sandbox.restrictions import
     RLIMIT_FSIZE_BYTES; print(RLIMIT_FSIZE_BYTES)"`).

4. **Agent context update** — `CLAUDE.md`'s "Active feature"
   block already points to 005; no SPECKIT markers exist, so
   amend the active-feature paragraph to point at 007 with a
   short hook to this plan (and link 005 + 006 + 004 as the
   priors). The plan reference goes inline as part of that
   paragraph.

**Output of Phase 1**: `contracts/amendment-004-code-generation.md`,
`quickstart.md`, `CLAUDE.md` updated.

## Re-check Constitution Check after Phase 1 design

Phase 1 produced no new entities, no new APIs, no new env vars, no
new dependencies. The only artifact crossing 007's boundary is the
amendment to `004/contracts/code-generation.md` — that is governed
by Constitution VII.c, which the amendment satisfies by documenting
the consequence-of-the-constraint paragraph.

**Gate result (post-design)**: PASS. No new violations introduced.
