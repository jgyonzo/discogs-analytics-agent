# Amendment to `004/contracts/code-generation.md` §3.1

This amendment is staged here so reviewers can see the exact prose
that will land in `specs/004-agent-v1/contracts/code-generation.md`
before the implementation phase modifies that file. The 007 task list
will instruct the implementer to copy the new clauses into 004 verbatim.

## What changes in 004's §3.1

Two changes:

1. **The `RLIMIT_FSIZE` value in the inline code sample** changes from
   `64 * 1024 * 1024` (64 MiB) to `2 * 1024 * 1024 * 1024` (2 GiB).

2. **A new "Sandbox file-size budget" subsection** is inserted
   immediately after the inline code sample, *before* the
   `wrapper_code` paragraph. The subsection is the verbatim text in
   the next section of this amendment.

No other lines in §3.1 change. §3.2, §3.3, §3.4 are untouched.

## Verbatim insertion: "Sandbox file-size budget"

> ### 3.1.1 Sandbox file-size budget (`RLIMIT_FSIZE`)
>
> `RLIMIT_FSIZE` is **process-wide** on Linux: it caps the size of
> *every* file the subprocess writes, not just the chart artifact.
> Two consumers share that cap under the V1 in-process subprocess
> sandbox:
>
> | Consumer | Typical size | Why it shares the cap |
> |---|---|---|
> | Plotly inline-JS chart HTML at `<artifact_dir>/<run_id>.html` | up to a few MB | Each successful run writes one. |
> | DuckDB intermediate spill at `<temp_directory>/duckdb_temp_storage_*.tmp` | up to ~1 GiB on full-catalog `GROUP BY` | DuckDB spills automatically when the operator's in-memory budget is exceeded; the temp_directory was pinned to `/tmp/duckdb` (a tmpfs) by the 006 fix, see Constitution VII.c. |
>
> A future sandbox-worker container or a per-mount `tmpfs … size=…`
> enforcement could give each consumer its own ceiling and let
> `RLIMIT_FSIZE` drop back down. That refactor is out of scope for
> V1 (`004/spec.md` Assumptions, `007/spec.md` § "Out of scope").
>
> **The chosen V1 budget**: `RLIMIT_FSIZE_BYTES = 2 * 1024 * 1024 *
> 1024` (2 GiB).
>
> **Sizing rationale**:
>
> - **Workload upper bound**: a release-grain `GROUP BY` against the
>   full April-2026 catalog (~17M unique releases × 8 bytes per
>   BIGINT × ~2× hash-table overhead) yields ~500 MB - 1 GiB of
>   intermediate state in a single spill file. 2 GiB gives 2-4×
>   headroom. Source:
>   [`specs/007-sandbox-fsize-budget/research.md` R-01](../../007-sandbox-fsize-budget/research.md).
> - **Bounding context**: 2 GiB is comfortably below the
>   `/tmp/duckdb` tmpfs default (≈ half of host RAM, ~8 GiB on a
>   16 GB dev laptop) and below typical container memory caps
>   (4-8 GiB). EFBIG fires before tmpfs ENOSPC, giving us one
>   predictable failure mode for over-spill cases. Source:
>   [`specs/007-sandbox-fsize-budget/research.md` R-02](../../007-sandbox-fsize-budget/research.md).
> - **Chart artifact**: well under the cap (worst observed in tests
>   ≈ 4 MB) — raising the cap does not shift any chart-artifact
>   concern.
>
> **Primary vs. secondary write-confinement**:
>
> - **Primary**: the per-run cwd jail at
>   `{ARTIFACTS_DIR}/{thread_id}/{run_id}/` confines all artifact
>   writes to one directory and rejects path-traversal attempts.
>   This is the load-bearing security control (FR-015 / FR-018).
> - **Secondary**: `RLIMIT_FSIZE` is the runaway-write backstop
>   that bounds *the size of any single file write* even within
>   the cwd jail. The cap is a disk-exhaustion safety net, not a
>   primary security boundary; future cap adjustments MUST be
>   judged against that role.
>
> **Forbidden adjustments**:
>
> - The cap MUST NOT be moved into an env var. It is a
>   security-relevant sandbox invariant; making it operator-tunable
>   would let a misconfiguration silently weaken the secondary
>   backstop. (Constitution VII.a applies to operator-tunable
>   knobs; this is not in that category.)
> - The cap MUST NOT be lowered without (a) verifying full-catalog
>   `GROUP BY` aggregations still spill below the new cap, and
>   (b) updating the rationale paragraph above with the new
>   workload sizing.
>
> **Named past incident**: the 64 MiB pre-fix value ate
> *every* aggregation against the published catalog with
> `IO Error: Could not write file
> "/tmp/duckdb/duckdb_temp_storage_DEFAULT-0.tmp": File too large`.
> See
> [`specs/007-sandbox-fsize-budget/spec.md`](../../007-sandbox-fsize-budget/spec.md)
> for the postmortem.

## Implementation note

The Python constant lives at
`agent/src/discogs_agent/sandbox/restrictions.py`:

```python
# Before (sized for chart HTML alone — see 007 postmortem)
RLIMIT_FSIZE_BYTES = 64 * 1024 * 1024

# After
RLIMIT_FSIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB; see contract §3.1.1
```

The constant's accompanying comment block in `restrictions.py` MUST
mirror the §3.1.1 rationale (workload + bounding context + named
incident citation), kept short — the contract is the canonical
prose; the constant comment is the operator-facing TL;DR.
