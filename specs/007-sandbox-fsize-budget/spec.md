# Feature Specification: Sandbox file-size budget — separate the chart-output and DuckDB-spill concerns

**Feature Branch**: `007-sandbox-fsize-budget`
**Created**: 2026-05-04
**Status**: Draft
**Input**: User description: "Bug fix: the sandbox sets RLIMIT_FSIZE = 64 MiB,
which caps every file the subprocess can write — including DuckDB's
/tmp/duckdb/duckdb_temp_storage_DEFAULT-0.tmp spill file. The 006 fix
moved the spill path off the read-only mount; this bug is the next
layer down — the spill size hits a 64 MiB ceiling that was sized for
the chart HTML, not for DuckDB intermediates."

## Background — what happened

A user submitted *"show the number of releases over time"* against the
real published DuckDB. The router classified `simple`, the generator
produced clean SQL, the safety check passed, the sandbox ran the
generated Python — and DuckDB raised:

```
IO Error: Could not write file
"/tmp/duckdb/duckdb_temp_storage_DEFAULT-0.tmp": File too large
```

The agent fell through to the controlled failure path
(`"I generated code but couldn't produce a valid chart after retrying"`),
so the user saw a coherent message rather than a crash — but **every**
non-trivial aggregation against the full Discogs catalog dies the same
way. The 005 + 006 work made style queries return correct results; this
bug makes those correct results unreachable at production scale.

## Why each fix shipped before this one wasn't enough

The agent has now eaten three sandbox/spill bugs in a row, each
unmasking the next:

1. **006 fix `d2b02f3`**: DuckDB's adjacent `<dbfile>.tmp/` spill dir
   couldn't be created next to a `:ro`-mounted DuckDB. Fix: pin
   `temp_directory="/tmp/duckdb"`, mount it as a tmpfs.
2. **This bug (007)**: now that the spill *path* is writable, the spill
   *size* trips `RLIMIT_FSIZE = 64 MiB`. The cap was sized in
   `004/contracts/code-generation.md §3.1` for the chart HTML
   ("64 MiB comfortably accommodates a Plotly inline-JS HTML"); it was
   never thought of as a budget for intermediate-state files.

The pattern: each layer of sandbox restriction was specced against a
single threat (DuckDB mutating its source file; the subprocess writing
arbitrary files; the chart artifact running away) without the joint
analysis showing that the *same* RLIMIT_FSIZE backstops both
concerns. Constitution VII.c (read-only runtime mechanics) covers the
mount; nothing covers the cumulative effect of multiple file-writing
clients sharing one process-wide write cap.

## The constraint that forced the conflation

`RLIMIT_FSIZE` on Linux is **process-wide, per file-write attempt**. A
single subprocess cannot have one cap for `/tmp/duckdb/*.tmp` and a
different cap for `<artifact_dir>/chart.html`. The contract may
*conceptually* split "spill budget" from "chart budget" but the kernel
enforces a single number. Any fix that wants to keep RLIMIT_FSIZE as a
backstop must pick a number that satisfies both consumers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Real-world aggregations succeed against the published catalog (Priority: P1)

A user submits any of the canonical analytical questions
(`"show the number of releases over time"`, `"Techno releases by
decade"`, `"label diversity by style"`, …) against the agent running on
the **full published DuckDB** — not just the seed fixture. The agent
generates SQL, the sandbox runs the code, DuckDB spills as much
intermediate state as the query naturally requires, and the user gets
a populated chart.

**Why this priority**: This is the "demo" and the headline. The agent
on the seed fixture is a unit test; the agent on the production catalog
is the actual product. Without this, the SC-002 anchor ("at least 5 of
6 golden questions succeed") only holds against the toy dataset.

**Independent Test**: Run any one of the failing aggregations against
the published DuckDB (the same one whose 17M-release decade GROUP BY
spilled past 64 MiB) and observe `status = "succeeded"` with a
non-empty preview and a chart artifact.

**Acceptance Scenarios**:

1. **Given** the agent is up against the published Discogs DuckDB,
   **When** the user submits *"show the number of releases over time"*,
   **Then** the response has `status = "succeeded"`, `row_count >= 6`
   (one per decade), the chart renders non-blank, and DuckDB's spill
   files completed without `IO Error: File too large`.
2. **Given** the same setup, **When** the user submits any of the 10
   canonical style queries from 005, **Then** all 10 succeed (no spill
   failures, no blank charts, no controlled-failure fallbacks).
3. **Given** a question that does **not** require spilling (small
   bounded result, e.g. *"how many decades does the catalog cover?"*),
   **When** the user submits it, **Then** it succeeds as before — this
   fix does not regress the no-spill path.

### User Story 2 — Runaway writes are still bounded (Priority: P2)

A reviewer wants assurance that raising the cap did not turn the
sandbox into an unbounded disk-write machine. They want to verify
that: (a) writes outside the per-run artifact directory are still
blocked by the cwd jail; (b) writes *inside* the artifact directory
or inside `/tmp/duckdb` are still capped by *some* RLIMIT_FSIZE
ceiling; (c) the documented ceiling is sized against a real-world
upper bound (full-catalog aggregation spill) and not just picked from
a hat.

**Why this priority**: SC-003 requires controlled failure on every
negative path. If the sandbox can now write 100 GB unchallenged, that
breaks the implicit "subprocess can't fill the host disk" property
that the 64 MiB cap was a side-effect implementation of.

**Independent Test**: A test deliberately attempts a write larger than
the new cap and observes a controlled failure (graceful EFBIG, no
agent crash, no traceback in the user response). Separately: the cwd
jail test from US1's `test_agent_safety_block.py` family still passes.

**Acceptance Scenarios**:

1. **Given** the new cap is *N* bytes (where *N* is the documented
   value), **When** generated code attempts to write a file larger
   than *N*, **Then** the sandbox returns a controlled failure
   (`status` in the failed-validation family) and the agent's response
   is operator-grade text, not a stack trace.
2. **Given** the new cap, **When** generated code attempts to write a
   file outside the per-run artifact directory, **Then** the cwd jail
   blocks it before RLIMIT_FSIZE is consulted — the existing
   `test_agent_safety_block` family still passes.
3. **Given** the published DuckDB is mounted `:ro`, **When** any test
   in the integration suite finishes, **Then** the DuckDB file's
   SHA-256 is byte-equal to its pre-test value (the existing SC-007
   anchor still holds).

### Edge Cases

- **Spill exceeds the new cap.** A pathological query (very wide
  `GROUP BY` with billions of distinct keys) could still hit EFBIG
  even at the raised cap. This MUST surface as a controlled failure
  on the run, not as a silent partial chart. The agent's existing
  retry-budget and validation-failure paths handle this — the new
  spec just confirms they continue to apply.
- **Container tmpfs fills before RLIMIT_FSIZE trips.** `tmpfs`
  without an explicit `size=` defaults to roughly half of host RAM on
  Linux. A spill larger than that hits `ENOSPC` ("No space left on
  device"). This too is a controlled failure path, distinct from
  EFBIG; both must be classified as `failed_validation` (or a
  documented sibling), never as `failed_internal`.
- **Cap chosen too low.** If the new cap accommodates seed-fixture
  spills but not full-catalog spills, the bug recurs at scale. The
  cap MUST be sized against the largest realistic intermediate-state
  size for a release-grain GROUP BY across the full catalog (~17M
  unique releases × ~16 bytes per hash entry × 14 decade buckets +
  materialization overhead).
- **Future sandbox refactor splits writes by directory.** If a future
  feature gives the sandbox a sandbox-worker container or a
  per-directory size enforcement (e.g. `mount tmpfs … size=…`), the
  process-wide RLIMIT_FSIZE could be lowered again. This spec's
  decisions are valid for the **V1 in-process subprocess sandbox**
  only, and the contract MUST cite that scope.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The sandbox MUST allow LLM-generated DuckDB code to
  spill intermediate state to its configured `temp_directory` up to a
  documented per-file ceiling. The ceiling MUST be sized to
  accommodate a release-grain GROUP BY against the full published
  Discogs catalog (~17M unique releases) without `IO Error: File too
  large`.
- **FR-002**: The same ceiling applies to chart artifact writes
  (`<artifact_dir>/<run_id>.html`). The contract MUST acknowledge
  that `RLIMIT_FSIZE` is process-wide on Linux and cannot be split
  between the two consumers under V1's in-process subprocess sandbox.
- **FR-003**: When a single write exceeds the ceiling, the sandbox
  MUST surface the failure as a controlled run outcome (the existing
  validation/sandbox failure path) — never as an unhandled exception
  on the run, never as a leaked traceback in the user-facing
  response.
- **FR-004**: The per-run artifact-directory cwd jail MUST remain the
  **primary** write-confinement control. `RLIMIT_FSIZE` is the
  **secondary** backstop against runaway writes; the contract MUST
  state this priority explicitly so future cap adjustments are
  judged against the right threat model.
- **FR-005**: The contract clause documenting the new ceiling MUST
  carry rationale: (a) the workload sizing (full-catalog GROUP BY
  spill estimate), (b) the bounding upper context (container memory
  cap and tmpfs default size), and (c) the named past incident (this
  feature, "007-sandbox-fsize-budget" + the failing query above).
- **FR-006**: The agent MUST continue to satisfy the existing
  Constitution VI guarantee — no DuckDB mutation, no ETL imports —
  unchanged. The fix MUST NOT relax any other sandbox restriction
  (`RLIMIT_CPU`, `RLIMIT_NOFILE`, `RLIMIT_NPROC`, `clean_env`).
- **FR-007**: The fix MUST be exercised by an automated regression
  test that fails before the fix and passes after — either against
  a spill-inducing fixture (a DuckDB large enough to force spill at
  the old cap but not at the new one) or against the production
  DuckDB gated behind an env var (parallel to `AGENT_DOCKER_SMOKE`).

### Key Entities *(include if data involved)*

- **SandboxFileBudget** (decision, not a runtime entity): the chosen
  ceiling N (in bytes) plus its rationale paragraph. Lives in
  `004/contracts/code-generation.md §3.1` and the Python constant
  `RLIMIT_FSIZE_BYTES` in `agent/src/discogs_agent/sandbox/restrictions.py`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The "show the number of releases over time" query
  (canonical reproducer captured in this spec's Background) succeeds
  end-to-end against the full published DuckDB, with `status =
  "succeeded"`, a non-empty preview, and a non-blank rendered chart —
  100% of three repeated attempts on a warm stack.
- **SC-002**: All 10 canonical style queries from 005 succeed
  end-to-end against the published catalog. Same anchor as 005's SC,
  re-verified at production data scale.
- **SC-003**: A regression test (per FR-007) demonstrably fails on
  the pre-fix `RLIMIT_FSIZE_BYTES = 64 MiB` and passes on the
  post-fix value — without modifying any other sandbox restriction.
- **SC-004**: A controlled-failure test that asks the sandbox to
  write a file larger than the new cap returns the documented
  failure status (failed-validation family) on 100% of runs; the
  user-facing response contains no `Traceback (most recent` and no
  internal path strings.
- **SC-005**: After the fix, the integration suite's existing
  byte-equality check (`test_duckdb_contract.py` or its successor)
  still passes — the published DuckDB is unmodified before and after
  the test batch (Constitution VI / SC-007 of 004 unaffected).
- **SC-006**: `004/contracts/code-generation.md §3.1` carries the
  new ceiling, the rationale paragraph (workload + bounding context
  + named incident), and the explicit "RLIMIT_FSIZE is process-wide;
  the cap is shared between spill and chart" caveat. Verified by a
  cross-artifact `/speckit-analyze` clean report after both this spec
  and the contract amendment land.

## Assumptions

- **V1 sandbox model**: The sandbox is an in-process subprocess on
  the agent host (not a sandbox-worker container, not gVisor, not
  Firecracker). Per `004/spec.md` Assumptions; nothing in 007
  changes this.
- **`temp_directory` lives at `/tmp/duckdb` (a tmpfs)**. Per
  `006/spec.md` Background and the existing
  `docker-compose.yml`. The size of that tmpfs is the host kernel's
  default (typically half of RAM); explicit `size=` is out of scope
  for 007 but called out in Edge Cases as a future-work hook.
- **Linux semantics for RLIMIT_FSIZE**: process-wide,
  per-file-write-attempt, returns `EFBIG` (errno 27). macOS hosts
  during local development behave the same way for sandbox purposes.
- **Workload sizing target**: the full published Discogs catalog
  (~17M unique releases as of the April 2026 snapshot — see
  `etl/README.md`'s ground-truth runbook). Future catalog growth
  beyond ~10× the 2026 size MAY require revisiting the cap; that is
  explicit future work, not a 007 deliverable.
- **No constitution amendment required**: Constitution VII.c covers
  read-only runtime mechanics; the new contract clause and the
  named-incident citation here satisfy the discipline already
  codified in 006.

## Out of scope

- **Splitting writes across multiple directories with separate size
  enforcement** (e.g. `mount tmpfs /tmp/duckdb size=2g; mount tmpfs
  <artifact_dir> size=128m`). Possible future improvement; would let
  RLIMIT_FSIZE drop back down. Listed in Edge Cases as the natural
  next refactor.
- **Switching to a sandbox-worker container** (which would isolate
  the spill directory at the OS level). Out of scope for V1 per
  `004/spec.md`; out of scope for 007 by extension.
- **Compressing DuckDB spill files** or asking DuckDB to use a
  different spill strategy. We are sizing the cap to the workload,
  not changing the workload.
- **Constitution amendment**. Principle VII (added by 006) already
  covers the discipline this fix exercises ("read-only runtime
  mechanics"). The new clause is contract-level, not constitution-level.
