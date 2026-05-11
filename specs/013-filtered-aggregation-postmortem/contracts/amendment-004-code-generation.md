# Amendment to `004/contracts/code-generation.md` — §3.4 failure modes + new §3.4.1

**Source feature**: `013-filtered-aggregation-postmortem`
**Target file**: `specs/004-agent-v1/contracts/code-generation.md`
**Predecessor amendment**: `specs/012-catalog-aggregation-postmortem/contracts/amendment-004-code-generation.md` (added §3.1.2 Sandbox memory budget)
**Update**: extend the `§3.4 Failure modes` table with the two new `exception_type` values introduced by 013; add a new `§3.4.1 Signal-aware failure mapping` subsection cross-referencing the canonical taxonomy contract.

---

## §3.4 Failure modes — extended table

The existing table (post-012) reads:

```markdown
| What happened | `exit_code` | `exception_type` | Validator response |
|---------------|-------------|------------------|--------------------|
| Clean success | 0 | None | `valid=true` |
| Python raised inside the script | non-zero | `<exception class name>` | `valid=false`; safety-or-validation retry edge engages |
| `RESULT` missing or wrong shape | 0 | `"no_result"` | `valid=false` |
| Wall-clock timeout | -9 | `"timeout"` | `valid=false` |
| Process killed by RLIMIT (rare) | non-zero | `"resource_limit"` | `valid=false` |
```

Replace it with:

```markdown
| What happened | `exit_code` | `exception_type` | Validator response |
|---------------|-------------|------------------|--------------------|
| Clean success | 0 | None | `valid=true` |
| Python raised inside the script | non-zero | `<exception class name>` | `valid=false`; safety-or-validation retry edge engages |
| `RESULT` missing or wrong shape | 0 | `"no_result"` | `valid=false` |
| Wall-clock timeout (harness watchdog) | -9 | `"timeout"` | `valid=false` |
| **External SIGKILL** (cgroup OOM-killer; **NEW 013**) | -9 | `"oom_killed"` | `valid=false`; single named rule `oom_killed`; response synthesizer emits memory-pressure hint |
| **Other signal kill** (SIGSEGV/SIGABRT/SIGTERM/…; **NEW 013**) | negative, ≠ -9 | `"sandbox_signaled"` | `valid=false`; legacy three-rule layering preserved |
| Positive non-zero exit (`sys.exit(n)`) | > 0 | `"nonzero_exit"` | `valid=false`; legacy three-rule layering |
| Process killed by RLIMIT (rare) | non-zero | `"resource_limit"` | `valid=false` |
```

Two rows added (`oom_killed`, `sandbox_signaled`); one row clarified (positive non-zero exit, previously implicit under the legacy `"nonzero_exit"` row); the existing `"timeout"` row labeled "harness watchdog" to disambiguate from the new external-SIGKILL row.

---

## New subsection: §3.4.1 Signal-aware failure mapping

Add this subsection immediately after the §3.4 table (above §3.1.2, or wherever document order places signal-aware behavior closest to the failure-modes table — implementer's discretion):

```markdown
### 3.4.1 Signal-aware failure mapping

*Added 2026-05-10 by `013-filtered-aggregation-postmortem`. Closes
the observability gap where any non-timeout SIGKILL surfaced as
opaque `exception_type = "nonzero_exit"`. Named incident: run
`b809ca52-12bc-4268-99d4-7603a5d0ecdd` ("what is the work of
Depeche Mode that has more versions?") on 2026-05-10.*

When `subprocess.Popen.returncode < 0` on POSIX, the value `-n`
indicates the process was terminated by signal `n`. The sandbox
runner MUST map these signal kills to named `exception_type`
values rather than the opaque `"nonzero_exit"`:

- `exit_code == -9` AND the harness's own `subprocess.TimeoutExpired`
  did NOT fire → `exception_type = "oom_killed"`. In the deployed
  cgroup, this is the kernel OOM-killer (the only realistic
  external producer of `-9`; the harness's own timeout path sets
  `exception_type = "timeout"` *before* this branch fires).
- `exit_code < 0` AND `exit_code != -9` AND the harness's timeout
  did NOT fire → `exception_type = "sandbox_signaled"`. The signal
  number is recorded in `exception_message` as `signal {n}`.

The canonical value set, decision table, and downstream-consumer
dispatch rules live in
`specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md`.

**Downstream consumers**:

- `chart_validator`: when `exception_type == "oom_killed"`, emit
  exactly ONE `ValidationError(rule="oom_killed", detail=<exception_message>)`,
  short-circuiting the legacy three-error layering
  (`nonzero_exit` + `exception_raised` + `result_missing`) that
  pre-013 produced for all SIGKILL paths.
- `response_synthesizer._build_result_block`: when
  `validation_result.errors[]` contains a rule of `"oom_killed"`,
  append a memory-pressure diagnostic hint to the result block
  before LLM paraphrasing. User-facing `final_response` will
  contain language about memory or query cost.
- `code_generator._format_failures` (repair-prompt assembler):
  no change. The function already surfaces
  `Sandbox exception: {exception_type}: {exception_message}`;
  the LLM receives the named cause on retry without any new
  plumbing.
```

---

## Why this matters

Pre-013, the `§3.4` table conflated two distinct producers of `exit_code == -9`:

1. **Harness-initiated SIGKILL** (timeout watchdog) — correctly labeled `"timeout"`.
2. **External SIGKILL** (cgroup OOM-killer, manual `docker kill`, etc.) — incorrectly labeled `"nonzero_exit"` by the catch-all branch.

This conflation is what 012's US2 was trying to fix at the runtime layer (via the `memory_limit=1GB` budget that was supposed to surface OOM as a catchable `OutOfMemoryException`). The Depeche Mode incident showed that approach is insufficient because DuckDB's `memory_limit` only governs DuckDB-heap allocations, not full process RSS — the cgroup OOM-killer is still reachable, and when it fires the conflation re-emerges.

013's amendment addresses the *observability* of this case: even when the OOM-killer fires, the named cause now flows through the system in a single inspection step. The mechanism that produces the OOM is unchanged; only its naming changes.

---

## Constitution VII.c compliance

This amendment is the symmetric *observability* analog of VII.c (Read-only runtime mechanics). VII.c says: declaring a runtime constraint MUST be accompanied by documenting its consequences. The `:ro` mount declaration in 004 was accompanied by VII.c's discussion of DuckDB spill mechanics. The cgroup memory-cap declaration (added by 012) is now accompanied by §3.4.1's discussion of OOM-kill mechanics. The pattern is intentional.

---

## Implementation pointer

Implementation lands as part of 013:

- `agent/src/discogs_agent/sandbox/runner.py` — catch-all branch at line 137 extended with signal-aware mapping.
- `agent/src/discogs_agent/tools/chart_validator.py` — new branch for `exception_type == "oom_killed"`.
- `agent/src/discogs_agent/graph/nodes/response_synthesizer.py` — `_build_result_block` extended with the new diagnostic-hint branch.
- New unit tests under `agent/tests/unit/` per `data-model.md` Entity 1 + 2.
- The 004 contract document itself — replaced per this amendment.
