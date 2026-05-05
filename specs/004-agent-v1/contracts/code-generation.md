# Contract: Code Generation & Sandbox

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md)
**Implements**: FR-005, FR-012, FR-015 – FR-018.

The code generator emits **full Python with embedded SQL**
that, when executed in the restricted sandbox, queries the
published DuckDB and writes a self-contained Plotly HTML
chart. The sandbox runs the code under a hard time budget,
captures the result, and returns artifact metadata.

This document is the contract between the LLM, the safety
checker, and the sandbox.

---

## 1. Generated-code shape

The LLM MUST produce a Python module that conforms to the
following template. The repair prompt re-states this template
on every retry so the model can self-correct.

```python
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go     # optional; only if used
from pathlib import Path
import os

DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]
ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(
    DB_PATH,
    read_only=True,
    config={"temp_directory": "/tmp/duckdb"},
)

sql = """
SELECT decade, COUNT(*) AS releases
FROM release_unique_view
WHERE decade IS NOT NULL
GROUP BY decade
ORDER BY decade
"""

df = con.execute(sql).df()

fig = px.bar(df, x="decade", y="releases", title="Releases by decade")
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")

RESULT = {
    "sql": sql,
    "chart_path": str(chart_path),
    "dataframe_preview": df.head(20).to_dict(orient="records"),
    "row_count": len(df),
    "chart_type": "bar",          # one of: bar, line, scatter, pie, histogram, table
}
```

### 1.1 Required structure

The generated code MUST:

1. Import `duckdb`, `pandas`, `plotly.express` (or
   `plotly.graph_objects` for charts that need it), `pathlib`,
   `os`. Other stdlib modules are fine. **Third-party imports
   beyond the above are forbidden** — the sandbox doesn't
   install packages and the few that exist in the agent's
   image are intentional.
2. Read `ANALYTICS_DUCKDB_PATH` from the environment.
3. Read `ARTIFACT_DIR` from the environment and `mkdir` it.
4. Open DuckDB with `read_only=True` AND
   `config={"temp_directory": "/tmp/duckdb"}`. The published DuckDB is
   bind-mounted `:ro` (see Constitution VII.c and `research.md` R-04),
   so DuckDB's default spill location adjacent to the file is unwritable.
   The `/tmp/duckdb` path is provided as a tmpfs mount on the
   `agent-api` service. Both kwargs MUST be present together; passing
   `read_only=True` without the temp_directory config will fail with
   `IO Error: Read-only file system` on any GROUP BY or sort that spills.
5. Define a single `sql = """..."""` string (or `query =
   """..."""`). The safety checker extracts from these
   names — see [`sql-safety.md` §3.1](./sql-safety.md).
6. Execute the SQL via `con.execute(sql).df()` and bind to
   `df`.
7. Generate a Plotly figure.
8. Write the figure to `ARTIFACT_DIR / "chart.html"` with
   `include_plotlyjs="inline"`.
9. Define a global `RESULT` dict at module level with the
   five keys below.

### 1.2 Required `RESULT` keys

| Key | Type | Notes |
|-----|------|-------|
| `sql` | string | The SQL that was executed, verbatim. |
| `chart_path` | string | Absolute path of the produced HTML. MUST be inside `ARTIFACT_DIR`. |
| `dataframe_preview` | list[dict] | `df.head(20).to_dict(orient="records")`. Empty list for legitimately empty results. |
| `row_count` | int | `len(df)` (the full df, not just the preview). |
| `chart_type` | string | One of: `bar`, `line`, `scatter`, `pie`, `histogram`, `box`, `area`, `table`. Used by the validator and recorded in `agent_artifacts.metadata`. |

`RESULT` MUST be defined at module level so the sandbox runner
can capture it via `runpy.run_path(...)["RESULT"]`.

---

## 2. Forbidden in generated code

The code-generator and repair prompts call these out
explicitly. The safety checker enforces some statically; the
sandbox restrictions enforce others at runtime.

| Forbidden | Enforced by |
|-----------|-------------|
| `import requests`, `import urllib`, `import socket`, `import http.client` | Code-generator prompt + sandbox env (no network namespace in V1, but the prompt is the primary guard) |
| `import subprocess`, `import os.system` | Prompt + AST scan in safety checker |
| `pip install`, `subprocess.run`, `os.system` | Prompt + sandbox env |
| `open("/etc/...")`, `open("../...")` | Prompt + sandbox cwd jail |
| `con = duckdb.connect(DB_PATH)` (without `read_only=True`) | Safety checker (rule `read_only_required`) |
| `con.execute("INSERT/UPDATE/DELETE/...")` | Safety checker (rule `ddl_dml`) |
| `read_csv(...)`, `read_parquet(...)`, `httpfs_*`, `s3_*` in SQL | Safety checker (rule `forbidden_function`) |
| References to `stg_*`, `clean_*`, `release_format_summary` | Safety checker (rule `forbidden_table`) |
| Writing files outside `ARTIFACT_DIR` | Sandbox cwd jail + RLIMIT_FSIZE |

---

## 3. Sandbox contract

### 3.1 Process invocation

```python
import subprocess, resource, os, signal

def preexec():
    resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024 * 1024, 2 * 1024 * 1024 * 1024))
    os.setsid()           # own process group so we can kill the tree on timeout

clean_env = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "ANALYTICS_DUCKDB_PATH": settings.ANALYTICS_DUCKDB_PATH,
    "ARTIFACT_DIR": str(artifact_dir),
    # NO OPENAI_API_KEY, NO DATABASE_URL, NO AWS_*
}

proc = subprocess.Popen(
    ["python", "-I", "-B", "-S", "-c", wrapper_code],
    cwd=str(artifact_dir),
    env=clean_env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    preexec_fn=preexec,
    start_new_session=True,
)
```

### 3.1.1 Sandbox file-size budget (`RLIMIT_FSIZE`)

`RLIMIT_FSIZE` is **process-wide** on Linux: it caps the size of
*every* file the subprocess writes, not just the chart artifact.
Two consumers share that cap under the V1 in-process subprocess
sandbox:

| Consumer | Typical size | Why it shares the cap |
|---|---|---|
| Plotly inline-JS chart HTML at `<artifact_dir>/<run_id>.html` | up to a few MB | Each successful run writes one. |
| DuckDB intermediate spill at `<temp_directory>/duckdb_temp_storage_*.tmp` | up to ~1 GiB on full-catalog `GROUP BY` | DuckDB spills automatically when the operator's in-memory budget is exceeded; the temp_directory was pinned to `/tmp/duckdb` (a tmpfs) by the 006 fix, see Constitution VII.c. |

A future sandbox-worker container or a per-mount `tmpfs … size=…`
enforcement could give each consumer its own ceiling and let
`RLIMIT_FSIZE` drop back down. That refactor is out of scope for
V1 (`004/spec.md` Assumptions, `007/spec.md` § "Out of scope").

**The chosen V1 budget**: `RLIMIT_FSIZE_BYTES = 2 * 1024 * 1024 *
1024` (2 GiB).

**Sizing rationale**:

- **Workload upper bound**: a release-grain `GROUP BY` against the
  full April-2026 catalog (~17M unique releases × 8 bytes per
  BIGINT × ~2× hash-table overhead) yields ~500 MB - 1 GiB of
  intermediate state in a single spill file. 2 GiB gives 2-4×
  headroom. Source:
  [`specs/007-sandbox-fsize-budget/research.md` R-01](../../007-sandbox-fsize-budget/research.md).
- **Bounding context**: 2 GiB is comfortably below the
  `/tmp/duckdb` tmpfs default (≈ half of host RAM, ~8 GiB on a
  16 GB dev laptop) and below typical container memory caps
  (4-8 GiB). EFBIG fires before tmpfs ENOSPC, giving us one
  predictable failure mode for over-spill cases. Source:
  [`specs/007-sandbox-fsize-budget/research.md` R-02](../../007-sandbox-fsize-budget/research.md).
- **Chart artifact**: well under the cap (worst observed in tests
  ≈ 4 MB) — raising the cap does not shift any chart-artifact
  concern.

**Primary vs. secondary write-confinement**:

- **Primary**: the per-run cwd jail at
  `{ARTIFACTS_DIR}/{thread_id}/{run_id}/` confines all artifact
  writes to one directory and rejects path-traversal attempts.
  This is the load-bearing security control (FR-015 / FR-018).
- **Secondary**: `RLIMIT_FSIZE` is the runaway-write backstop
  that bounds *the size of any single file write* even within
  the cwd jail. The cap is a disk-exhaustion safety net, not a
  primary security boundary; future cap adjustments MUST be
  judged against that role.

**Forbidden adjustments**:

- The cap MUST NOT be moved into an env var. It is a
  security-relevant sandbox invariant; making it operator-tunable
  would let a misconfiguration silently weaken the secondary
  backstop. (Constitution VII.a applies to operator-tunable
  knobs; this is not in that category.)
- The cap MUST NOT be lowered without (a) verifying full-catalog
  `GROUP BY` aggregations still spill below the new cap, and
  (b) updating the rationale paragraph above with the new
  workload sizing.

**Named past incident**: the 64 MiB pre-fix value ate
*every* aggregation against the published catalog with
`IO Error: Could not write file
"/tmp/duckdb/duckdb_temp_storage_DEFAULT-0.tmp": File too large`.
See
[`specs/007-sandbox-fsize-budget/spec.md`](../../007-sandbox-fsize-budget/spec.md)
for the postmortem.

The `wrapper_code` is a small Python harness (committed at
`agent/src/discogs_agent/sandbox/wrapper.py.tmpl`) that:

1. Reads the user-generated code from a file path passed as
   the first arg.
2. Executes it via `runpy.run_path(...)`.
3. Serializes the resulting `RESULT` dict (or the captured
   exception) to JSON and prints to stdout on a known marker
   (`__AGENT_RESULT_BEGIN__`...`__AGENT_RESULT_END__`).

The harness ensures `RESULT` is captured even if the script's
last statement is a side effect — runpy gives us the module
namespace.

### 3.2 Timeout

```python
try:
    stdout, stderr = proc.communicate(timeout=settings.SANDBOX_TIMEOUT_SECONDS)
    exit_code = proc.returncode
    exception_type = None
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    exit_code = -9
    exception_type = "timeout"
    stdout, stderr = proc.communicate()
```

### 3.3 Output capture

- `stdout` and `stderr` are decoded UTF-8, capped at 16 KiB
  each (truncation noted with a sentinel).
- The `RESULT` block is extracted from stdout via the begin/end
  markers; remaining stdout is the "natural" stdout (usually
  empty).
- If the markers are missing → `RESULT = None`,
  `exception_type = "no_result"`.

### 3.4 Failure modes

| What happened | `exit_code` | `exception_type` | Validator response |
|---------------|-------------|------------------|--------------------|
| Clean success | 0 | None | `valid=true` |
| Python raised inside the script | non-zero | `<exception class name>` | `valid=false`; safety-or-validation retry edge engages |
| `RESULT` missing or wrong shape | 0 | `"no_result"` | `valid=false` |
| Wall-clock timeout | -9 | `"timeout"` | `valid=false` |
| Process killed by RLIMIT (rare) | non-zero | `"resource_limit"` | `valid=false` |

---

## 4. The count rule (FR-012 / SC-008)

The code-generator prompt MUST include this paragraph
verbatim (the test `test_count_rule_in_prompt` asserts it):

> **Critical rule for `release_fact`**: this table has grain
> *one row per release × style*. To count distinct releases,
> use `COUNT(DISTINCT release_id)` or query
> `release_unique_view` (which has grain *one row per
> release*) instead. Never use `COUNT(*) FROM release_fact`
> unless you genuinely want to count release-style rows.

The "Techno over time" golden test (`test_golden_techno_over_time.py`)
asserts that the persisted `agent_runs.generated_sql` for the
question "Show the evolution of Techno releases over time"
contains either `COUNT(DISTINCT release_id)` or queries
`release_unique_view` — both are acceptable answers.

---

## 5. `master_fact` conditional generation

The code-generator prompt receives `state.schema_context`,
which carries `has_master_fact`. The prompt instructs the
model to:
- Use `master_fact` for "works", "version count", or
  "main release" questions when `has_master_fact == true`.
- For all other questions, prefer `release_unique_view` /
  `release_fact` with the count rule.

When `has_master_fact == false`, the router should classify
`master_fact`-only questions as `unsupported` (so we never
reach code generation). If the router lets one through, the
safety checker blocks it as `forbidden_table` (since
`master_fact` isn't in the allowlist for *this* schema
context).

---

## 6. Plotly HTML constraints

- `include_plotlyjs="inline"` — the JS must be self-contained.
  This produces ~3 MiB files; well under our 64 MiB FSIZE
  limit.
- Title MUST be set on every chart (helps reviewers).
- Charts MUST use the `df` variable (not raw SQL execute
  results) so the dataframe preview matches what the chart
  renders.

---

## 7. Testing

| Test | Stratum | Asserts |
|------|---------|---------|
| `test_sandbox_clean_success` | unit | A hand-written valid script produces RESULT, exit 0. |
| `test_sandbox_timeout` | unit | A `time.sleep(60)` script is killed at SANDBOX_TIMEOUT_SECONDS. |
| `test_sandbox_no_network` | unit | An `import urllib.request; urllib.request.urlopen('http://example.com')` script either fails-closed (no network) OR is forbidden by the prompt — the test documents the actual V1 behavior (network namespace is *not* enforced; reliance is on prompt + safety). |
| `test_sandbox_no_pkg_install` | unit | A `pip install x` shell-out produces non-zero exit (no `pip` on PATH inside the cleaned env). |
| `test_sandbox_no_secret_leak` | unit | The harness sees no `OPENAI_API_KEY` / `DATABASE_URL` / `AWS_*` in os.environ. |
| `test_sandbox_writes_only_in_artifact_dir` | unit | Attempting to write `/tmp/x.html` either succeeds (it's outside ARTIFACT_DIR — the validator catches it later as a chart_path violation) — the *prompt* is the primary guard; the test asserts the validator's chart_path check rejects the produced file. |
| `test_sandbox_runs_seed_query` | integration | Real seed.duckdb + a hand-written valid script: chart appears, RESULT shape correct. |
| `test_count_rule_in_prompt` | unit | The prompt template contains the count-rule paragraph. |
| `test_golden_techno_over_time` | golden | LLM-stub returns the canonical Techno query; persisted SQL passes safety; sandbox produces a chart; saved SQL contains `COUNT(DISTINCT release_id)` or `release_unique_view`. |
