# Phase 0 Research: `RLIMIT_FSIZE_BYTES` sizing

The single design question for 007 is **what byte-count to choose for
the sandbox's `RLIMIT_FSIZE`** so that:

- A release-grain `GROUP BY` against the full published Discogs
  catalog (~17M unique releases) succeeds end-to-end without
  `IO Error: File too large`.
- The cap remains a meaningful runaway-write backstop for the chart
  artifact and any other write the subprocess might attempt.
- We don't wander off into "effectively unbounded" territory and
  lose the disk-exhaustion property the original 64 MiB constant
  was an accidental implementation of.

## R-01: Workload sizing — full-catalog `GROUP BY` spill

**Workload anchor**: the canonical reproducer captured in
[`spec.md` Background](./spec.md#background--what-happened):

```sql
SELECT decade, COUNT(DISTINCT release_id)
FROM release_unique_view
GROUP BY decade
ORDER BY decade
```

against the full published DuckDB (April-2026 snapshot,
~17M unique releases — see `etl/README.md`'s ground-truth runbook).

**DuckDB execution mechanics** (per the DuckDB docs and the
`duckdb_temp_storage_*.tmp` file naming we observed):

- DuckDB builds a hash-aggregate operator over `decade` with a
  `COUNT(DISTINCT release_id)` aggregate state per group.
- Distinct-tracking is implemented as a per-group hash set of
  `release_id` values (BIGINT, 8 bytes each).
- When the aggregate-state size exceeds the per-operator memory
  budget, DuckDB spills the partitioned hash table to
  `<temp_directory>/duckdb_temp_storage_DEFAULT-N.tmp` files.

**Spill-size estimate**:

| Term | Value | Notes |
|---|---|---|
| Unique releases | ~17,000,000 | Full April-2026 catalog. |
| `release_id` size | 8 bytes | BIGINT. |
| Hash-table overhead | ~2× | Probing + load-factor headroom. |
| Decade groups | ~14 | 1880s through 2020s, sparse early. |
| Worst-case-partitioned spill per group | ~270 MB | 17M × 8B × 2 if pathologically all in one group. |
| Realistic spill (across all groups, single file) | ~500 MB – 1 GiB | DuckDB's columnar-compressed spill format usually compresses below the in-memory rep, but the `duckdb_temp_storage_*` format is designed for fast roundtrip, not compactness. |

A single spill file landing at **≤ 1 GiB** is the realistic upper
bound for this query at this catalog size.

## R-02: Bounding context — tmpfs and container memory

The chosen cap must sit comfortably below two harder ceilings so
that EFBIG fires before either of them does — giving us **one**
predictable failure mode for over-spill cases.

| Ceiling | Source | Typical value | Notes |
|---|---|---|---|
| Host tmpfs (default) | Linux kernel default for `tmpfs` mounts without explicit `size=` | ≈ half of host RAM (≈ 8 GiB on a 16 GB dev laptop) | Docker passes through unless overridden. |
| Container memory cap | `docker compose` default | unbounded by default (uses host RAM) | A production deploy SHOULD set this; not 007's concern. |
| Bind-mounted host disk for `./artifacts/` | Host filesystem | ≥ tens of GiB | Not a concern at the per-file level — RLIMIT_FSIZE is the bound. |

**2 GiB** sits comfortably below the tmpfs default (8 GiB) and is
~4× the worst realistic spill — enough headroom to not be brittle,
not so much that we lose the backstop meaning.

## R-03: Decision

**`RLIMIT_FSIZE_BYTES = 2 * 1024 * 1024 * 1024` (2 GiB).**

**Rationale**:

- ~2-4× headroom above the canonical reproducer's spill estimate
  (R-01).
- Comfortably below tmpfs default and typical container memory
  caps (R-02), so EFBIG fires before tmpfs ENOSPC.
- Accommodates the chart artifact (worst observed ≈ 4 MB) trivially.
- Bounds runaway writes well below the host disk allocation —
  retains the original constant's "this subprocess can't fill the
  disk" property at the right scale.

**Alternatives considered**:

| Option | Verdict | Why |
|---|---|---|
| **64 MiB** (status quo) | ❌ | Trips on the canonical reproducer. |
| **256 MiB** | ❌ | Still trips on full-catalog GROUP BY at peak spill. |
| **1 GiB** | ⚠️ | Right at the edge of R-01's worst realistic spill. Picks fights over a small saving in disk-backstop margin. |
| **2 GiB** | ✅ | Chosen. |
| **4 GiB** | ❌ | Wastes margin. Doesn't unlock any V1-era query that 2 GiB doesn't. |
| **8 GiB+** | ❌ | Brushes against tmpfs default; only sensible on production VMs with ≥ 32 GB RAM; premature for V1. |
| **Drop RLIMIT_FSIZE entirely** | ❌ | The cwd jail does not bound writes *inside* the artifact dir; without RLIMIT_FSIZE, a malformed chart could fill the host bind mount. |
| **Per-directory `tmpfs … size=…` enforcement** | ❌ for V1, future work | Would let RLIMIT_FSIZE drop back down. Out of scope per `spec.md` § "Out of scope". |
| **Sandbox-worker container** | ❌ for V1 | Out of scope per `004/spec.md`. |
| **Move cap into env var (`SANDBOX_FSIZE_LIMIT_BYTES`)** | ❌ | Constitution VII.a covers operator-tunable knobs. A security-critical sandbox invariant is not in that category — making it env-tunable would let a misconfiguration silently weaken the secondary backstop. |

## R-04: Failure-mode classification

When a spill exceeds 2 GiB (rare but possible — pathological
`COUNT(DISTINCT)` over very-high-cardinality non-decade groupings),
the agent MUST surface a controlled failure on the run. Two
distinguishable kernel signals are involved:

| Kernel signal | Meaning | Agent classification | Notes |
|---|---|---|---|
| `EFBIG` (errno 27) | Write exceeds RLIMIT_FSIZE | `failed_validation` (existing path) | Sandbox returns non-zero exit + DuckDB `IO Error`; the validator catches it and re-prompts within retry budget; if retries exhaust, `final_response` is operator-grade text per FR-024. |
| `ENOSPC` (errno 28) | tmpfs full | `failed_validation` (same path) | Distinguishable in logs by the error string; same user-facing failure shape. |

**Decision**: both surface as `failed_validation` (or its sibling
status if 005's `succeeded_empty` taxonomy demands a separate
bucket). No new status enum needed. The integration test in
Phase 2 (`test_sandbox_fsize_budget.py`) MUST exercise the
post-fix EFBIG path against a synthetic over-cap write and assert
the controlled-failure shape.

## R-05: Test-fixture sizing

**Goal**: a test that fails at the pre-fix 64 MiB cap and passes at
the post-fix 2 GiB cap, *without* requiring the 17M-release
production DuckDB to live in `agent/tests/fixtures/`.

**Approach**:

1. Build (in-test, idempotent) a small `spill_seed.duckdb` with
   ~5M synthetic release rows (single column, BIGINT release_id).
   This is enough to force a spill > 64 MiB on a `COUNT(DISTINCT)`
   GROUP BY but stays under 200 MB on disk and under 2 GiB during
   spill.
2. Run a generated-code-shape Python script through the existing
   sandbox runner against the synthetic DuckDB.
3. Assert: with the *current* `RLIMIT_FSIZE_BYTES`, the run
   succeeds. (We don't test the pre-fix value at runtime — that
   would require monkeypatching the constant inside a subprocess,
   which the sandbox restrictions explicitly defeat.) Instead, we
   add a *unit-style* assertion that `RLIMIT_FSIZE_BYTES >=
   1 * 1024 * 1024 * 1024` so a future "tighten-the-cap" change
   that reverts the fix immediately fails CI.

**Alternative considered**: use the production DuckDB gated behind
`AGENT_PUBLISHED_DUCKDB_SMOKE=1` (parallel to `AGENT_DOCKER_SMOKE`).
Worth doing later if the synthetic fixture ever stops mirroring
the real failure mode, but for V1 the synthetic version is
deterministic, fast, and committable.

## R-06: Future work hook (out of scope for 007)

A natural follow-up — *not* part of 007 — would be to give
`/tmp/duckdb` an explicit `tmpfs … size=2g` in `docker-compose.yml`
and lower RLIMIT_FSIZE back to ~128 MiB scoped to the artifact
directory only. That requires either:

- Splitting the sandbox subprocess into multiple cgroups with
  per-mount enforcement, or
- Moving to a sandbox-worker container with its own filesystem.

Both are listed as future work in the V1 spec. 007 stays inside the
in-process subprocess model and accepts the process-wide cap as a
constraint.
