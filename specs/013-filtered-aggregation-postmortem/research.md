# Research: 013-filtered-aggregation-postmortem

**Date**: 2026-05-10
**Purpose**: Resolve the open design questions identified in `plan.md`'s Technical Context before drafting contracts. Each section names a decision, the rationale, and the alternatives considered.

---

## R1. Exact set of `exception_type` values

**Decision**: Two new values added to the existing taxonomy:

| `exit_code` | Origin | New `exception_type` | `exception_message` shape |
|-------------|--------|----------------------|---------------------------|
| `-9` (when harness's own `subprocess.TimeoutExpired` did NOT fire) | external SIGKILL — in practice, the cgroup OOM-killer | `"oom_killed"` | `"kernel SIGKILL (cgroup OOM-killer); exit_code=-9; sandbox exceeded memory budget"` |
| Any other `exit_code < 0` (when `exception_type is None` at the catch-all branch) | other signal kill (SIGSEGV/-11, SIGABRT/-6, SIGTERM/-15, …) | `"sandbox_signaled"` | `"sandbox killed by signal {n}; exit_code={exit_code}"` where `n = -exit_code` |

The pre-existing values (`"timeout"`, `"parse_failed"`, `"no_result"`, `"nonzero_exit"`, plus Python-side `_error` strings) are preserved with their current semantics.

**Rationale**:

- **Two values, not one umbrella**: SIGKILL specifically maps to OOM in the deployed cgroup because the harness's own timeout path *also* uses SIGKILL but sets `exception_type = "timeout"` before the catch-all fires (`sandbox/runner.py:107–108`). The only remaining producer of `-9` is the cgroup OOM-killer (or, in dev, a manual `docker kill`). Naming the dominant case (`oom_killed`) lets the validator and response synthesizer specialize their downstream behavior. Other negatives are rarer and don't have a single dominant cause; grouping them under `"sandbox_signaled"` with the signal number in the message is honest.
- **Two values, not five**: a per-signal taxonomy (`"sigsegv"`, `"sigabrt"`, …) would be over-fit. The signal number is preserved in `exception_message`; downstream code that genuinely needs to branch on SIGSEGV can parse it out. Most consumers only care about OOM vs. everything-else.
- **Deterministic per FR-005**: the mapping is a pure function of `(exit_code, harness_timeout_fired)`. No randomness, no LLM, no env-variable knob.

**Alternatives considered**:

- *Single value `"sandbox_signaled"` for all negatives*: rejected. Would force the validator + response synthesizer to re-parse `exit_code` to specialize OOM behavior, defeating the point of naming the cause.
- *Per-signal taxonomy*: rejected as over-fit. Re-evaluatable if future incidents prove a dominant SIGSEGV class exists.
- *Operator-configurable label*: rejected per Constitution VII.a — these are taxonomy constants, not configuration.

---

## R2. Where the canonical taxonomy lives

**Decision**: A new contract document at `specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md` (FR-014). The `004/contracts/code-generation.md §3.4 "Failure modes"` table gains two new rows referencing the new doc as the source of truth (FR-013 amendment).

**Rationale**: 004's §3.4 is the right consumer surface but is itself a table — too dense to host the full taxonomy with all its caveats. A standalone 013-owned doc is cleaner. The pattern (table on the consumer side, full canonical doc on the producer side) mirrors how 010's JSONB invariant works (`004/postgres-schema.md §7` references the SQLAlchemy `_SanitizedJSON` chokepoint).

**Alternatives considered**:

- *Embed the table directly in `004/code-generation.md`*: rejected — would make 004 the owner of decisions reached in 013, blurring SDD provenance.
- *Skip the standalone doc, only amend 004*: rejected — the taxonomy is normative and deserves its own document the unit test can grep against.

---

## R3. User-facing OOM message wording

**Decision**: When `validation_result.errors[]` contains a rule of `"oom_killed"`, the response synthesizer's `_build_result_block` (in `agent/src/discogs_agent/graph/nodes/response_synthesizer.py:92`) MUST append a "Diagnostic hint" of the form:

> *Diagnostic hint: the query exceeded the sandbox's memory budget and was terminated by the kernel. This usually means the query touched too many rows. Try narrowing the scope — filter to a single artist, year, country, or genre — or ask for a smaller slice of the catalog.*

The final user-facing string the response synthesizer emits is not byte-locked (the model paraphrases the result block into prose); SC-006's verification is a substring check for any of `"memory"`, `"too heavy"`, `"narrow your question"`, `"reduce scope"`.

**Rationale**: the precedent is the `succeeded_empty` case already at `response_synthesizer.py:107`, which appends a parallel "Diagnostic hint" with style-vs-genre guidance. Adding a sibling branch for `oom_killed` follows the established pattern exactly. The wording aims for "this is what happened; here is what to try" — actionable enough that the user has a next step.

**Alternatives considered**:

- *Hardcode the user-facing string and bypass the response_synthesizer LLM*: rejected. The synthesizer's prose-shaping is what makes the agent's voice consistent; byte-locking strings around it would create a tonal mismatch.
- *Only update the result_block; leave the synthesizer prompt unchanged*: accepted. The synthesizer prompt already instructs the model to use the result block as ground truth; adding a hint there is sufficient.

---

## R4. Repair-prompt plumbing for the new `exception_type`

**Decision**: **No new code wiring needed** — the plumbing already exists at `agent/src/discogs_agent/graph/nodes/code_generator.py:103–108`:

```python
execution = state.get("execution_result")
if isinstance(execution, dict):
    if execution.get("exception_type"):
        parts.append(
            f"Sandbox exception: {execution['exception_type']}: {execution.get('exception_message', '')}"
        )
```

When FR-001 lands, the LLM sees `Sandbox exception: oom_killed: kernel SIGKILL (cgroup OOM-killer); exit_code=-9; sandbox exceeded memory budget` in the repair prompt's `{failure_details}` block (per `repair_code.md:27–29`). The named cause reaches the LLM "for free."

**Rationale**: this is the load-bearing happy accident — `_format_failures` was already designed to surface whatever string `exception_type` carries. FR-004 is therefore satisfied by FR-001 alone; no code change in the repair-prompt path is required. The repair_code.md prompt's `{failure_details}` placeholder is the contractual surface.

**Alternatives considered**:

- *Add a dedicated `oom_hint:` line in the repair prompt assembly*: considered, rejected as redundant. The exception_type + message tuple already conveys "OOM" in plain English; the LLM doesn't need a more explicit nudge to pick a cheaper plan.
- *Reshape repair_code.md to include explicit "if oom_killed, prefer release_fact + COUNT(DISTINCT)" guidance*: out of scope. The repair prompt already carries the Critical rule about `release_unique_view` (lines 37–42); after FR-009 lands, that rule is tightened to "any JOIN or GROUP BY," which is the actual fix.

---

## R5. Glossary entry #3 exact replacement text

**Decision**: replace the current entry #3 (from the 012 amendment) with the following byte-equivalent wording in `_DOMAIN_GLOSSARY`:

```text
3) release_fact has grain release × style. For counts of unique
   releases, use `SELECT X, COUNT(DISTINCT release_id) FROM
   release_fact GROUP BY X` — this only tracks per-X distinct
   sets and is cheap. DO NOT use release_unique_view in any
   JOIN or GROUP BY, regardless of WHERE filters: the view is
   defined as `SELECT DISTINCT (~33 columns) FROM release_fact`
   and forces DuckDB to materialize the entire deduplicated set
   (~19M rows × 33 cols), which typically OOMs the sandbox even
   when the query has selective WHERE clauses on a joined table
   (the planner cannot push the predicate through the view's
   DISTINCT). release_unique_view is ONLY safe for spot-check
   queries that filter directly on a single release literal
   (e.g., `SELECT * FROM release_unique_view WHERE release_id = N`).
   Never use `COUNT(*) FROM release_fact` for release counts (it
   counts release × style rows, not releases).
```

The deltas from 012's wording:

1. *"for catalog-wide aggregations"* → *"in any JOIN or GROUP BY, regardless of WHERE filters"* — closes the loophole the Depeche Mode case exploited.
2. *"forces DuckDB to materialize the entire deduplicated set ... which spills GBs of temp even for trivial GROUP BYs"* → *"which typically OOMs the sandbox even when the query has selective WHERE clauses on a joined table (the planner cannot push the predicate through the view's DISTINCT)"* — names the actual failure mode the user just hit (a critical clue for the LLM that filtering doesn't help).
3. *"is fine for spot-check queries against a single release (e.g., `WHERE release_id = N`), but never for catalog-wide GROUP BYs"* → *"is ONLY safe for spot-check queries that filter directly on a single release literal (e.g., `SELECT * FROM release_unique_view WHERE release_id = N`)"* — narrowed carve-out: the predicate has to be on a literal release_id, not filtered indirectly through a join.

The keyword-assertion test `test_schema_context_glossary_contains_style_vs_genre_rule` continues to pass — all four keywords (`primary_genre`, `style`, `decade`, `year`) survive the rewrite (the entries that carry them are #1, #2, #4, not the rewritten #3). Verified by inspection.

**Rationale**: the rewrite tightens what was loose ("catalog-wide" was the LLM's escape hatch) and *adds operational truth* (predicate-pushdown failure is the actual cause). The narrowed carve-out language ("filter directly on a single release literal") is a positive specification — easier for the LLM to apply than a list of forbidden cases.

**Alternatives considered**:

- *"NEVER use release_unique_view"* (no carve-out): rejected — would block the legitimate spot-check use case (`WHERE release_id = N` is a constant-time index lookup, cheap regardless of the view's DISTINCT).
- *"Use release_unique_view only when the EXPLAIN shows a pushdown of WHERE through the DISTINCT"*: rejected — the LLM has no visibility into EXPLAIN; this would be aspirational text.
- *Removing entry #3 entirely and forbidding the view in the rendered allowlist*: considered. Would be cleaner but loses the spot-check carve-out, and removing tables from the allowlist is a Principle V surface change that 013 explicitly chose to avoid.

---

## R6. `code_generator.md` and `repair_code.md` mirror text

**Decision**: same wording as R5, formatted as a bullet under the "Critical rule for counting releases" section in `code_generator.md` and as an updated Critical-rules bullet at `repair_code.md:37–42`. The mirror is shorter (a paraphrase) — full reasoning lives in the glossary; the prompts get the rule-of-thumb version per VII.b's carve-out. Exact prose:

```text
- For release counts: use `COUNT(DISTINCT release_id) FROM release_fact GROUP BY ...`.
  DO NOT use `release_unique_view` in any JOIN or GROUP BY, regardless of WHERE
  filters — its `SELECT DISTINCT *` definition materializes the full 19M-row set
  and OOMs the sandbox even on filtered queries. The view is ONLY safe for
  spot-check queries that filter directly on a single release literal (e.g.,
  `WHERE release_id = 12345`). NEVER `COUNT(*) FROM release_fact` for release
  counts.
```

**Rationale**: same wording shape as the glossary entry, dropped to bullet density per the prompts' role.

**Alternatives considered**: none — the prose is mechanically derived from R5.

---

## R7. Q1 description rewrite in `008/contracts/curated-questions.md:18`

**Decision**: replace

```text
- **description**: `Basic decade-grain trend using release_unique_view.`
```

with

```text
- **description**: `Basic decade-grain release count using COUNT(DISTINCT release_id) FROM release_fact GROUP BY decade.`
```

**Rationale**: matches operational reality (the agent post-012 already generates this exact SQL shape for Q1). Removes the stale "uses release_unique_view" claim that conflicts with 013's glossary tightening.

**Alternatives considered**:

- *Leave Q1 description as-is*: rejected by user direction during spec drafting.
- *Add a footnote rather than replace*: rejected — the description is a one-liner; a footnote would be more confusing than a clean replacement.

---

## R8. New tests for the runner signal-mapping branch

**Decision**: add `agent/tests/unit/test_sandbox_signal_mapping.py` with three test cases:

1. `test_sigkill_external_yields_oom_killed`: construct a `SandboxOutcome` precursor with `exit_code=-9` and `exception_type=None` (the catch-all state). After the new branch fires, `exception_type == "oom_killed"`.
2. `test_sigkill_via_harness_timeout_preserved`: simulate the existing timeout path. `exception_type == "timeout"`, NOT relabeled to `"oom_killed"` (the timeout branch sets it before the catch-all).
3. `test_other_negative_exit_yields_sandbox_signaled`: `exit_code=-11` (SIGSEGV) with `exception_type=None` produces `exception_type == "sandbox_signaled"` and `exception_message` contains "signal 11" or equivalent.

For the validator (`agent/tests/unit/test_chart_validator_oom_rule.py`), two test cases:

1. `test_oom_killed_produces_single_named_rule`: feed a `SandboxOutcome`-shaped dict with `exception_type="oom_killed"`; assert `errors` contains exactly one entry with `rule="oom_killed"`, not the legacy three-error layering.
2. `test_unknown_failure_keeps_legacy_layering`: feed `exception_type="nonzero_exit"`; assert the legacy three-error layering is preserved (regression guard).

**Rationale**: the runner and validator are pure-function-ish surfaces; unit tests are sufficient. The integration-test golden update (FR-010) covers the prompt path.

**Alternatives considered**:

- *Integration test that induces an actual SIGKILL*: nice-to-have but flaky (depends on the cgroup behaving identically in CI). Unit-level synthetic outcomes are deterministic and cheap.

---

## R9. Successor-spec pointer (FR-015)

**Decision**: write a thin pointer document at `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` (named for clarity even though 014 doesn't exist yet). The document declares:

- The problem being deferred: `release_unique_view`'s `SELECT DISTINCT (~33 columns)` materialization is the root cause of every catalog-aggregation OOM. 012 + 013 are workarounds at the agent/prompt layer; the *real* fix is an ETL-side rewrite.
- Provisional successor spec name: `014-release-unique-view-materialization` (subject to confirmation when the spec is actually opened).
- Component: `etl/` (Principle VI separation — agent component will not be modified by 014).
- Suggested implementation directions: (a) make the view a materialized table built once at ETL time via `CREATE TABLE … AS SELECT DISTINCT ON (release_id) …` or equivalent; (b) drop the view entirely and replace with per-release summary tables (one for release-grain numerics, one for boolean flags, etc.); (c) keep the view but redefine it without the 33-column DISTINCT (e.g., select only the columns actually needed at the view's grain).
- Acceptance criterion for 014 to close 013's lingering gap: catalog-scale `AVG(track_count) FROM release_unique_view GROUP BY decade` returns within the sandbox memory budget.
- Until 014 lands: 013's glossary tightening remains in force.

**Rationale**: explicitly naming the deferred work — including a provisional spec number — keeps it traceable. Without this pointer, the deferral lives only in 013's Out-of-Scope section; with it, the next `/speckit-specify` for ETL has a starting point.

**Alternatives considered**:

- *Just mention the deferral in 013's spec.md and skip the pointer doc*: rejected — the spec already does that, but a contracts/ doc makes the deferral grep-discoverable from the future ETL spec's drafting session.
- *Open 014 now as part of 013's PR*: rejected — out of scope for 013's user direction; 014 is its own component (ETL), its own concerns, and deserves its own conversation.

---

## R10. Edge-case validation: does the new wording regress Q4 ("Compare Vinyl and CD releases by decade")?

**Decision**: check `008/contracts/curated-questions.md` for Q4's expected SQL shape, then mentally apply the new glossary wording, then confirm the LLM still has a clean path.

Q4's natural form is:

```sql
SELECT decade, primary_format_group, COUNT(DISTINCT release_id) AS releases
FROM release_fact
WHERE primary_format_group IN ('Vinyl', 'CD')
GROUP BY decade, primary_format_group
```

No `release_unique_view` reference. The new glossary wording neither requires nor forbids anything different from what 012 already established. Q4 is not regressed. ✅

Same check for Q1, Q2, Q3, Q5, Q6, Q7: each is either a `release_fact + COUNT(DISTINCT)` shape or a non-count question already steered toward `release_fact` (subgenre filters, etc.). None of the seven engages with the JOIN/GROUP-BY ban beyond what 012 already covered.

**Rationale**: SC-004 (no curated-question regressions) is provable by inspection — none of the seven curated questions has a JOIN-against-release_unique_view shape that 013 newly forbids.

---

## R11. Open questions surfaced during research — NONE

All design questions raised by `plan.md`'s Technical Context are resolved above. No `[NEEDS CLARIFICATION]` markers remain.

## Summary of file edits the implementation will perform

For tasks.md (next phase) to enumerate:

| File | Change | FR(s) |
|------|--------|-------|
| `agent/src/discogs_agent/sandbox/runner.py` | Extend catch-all branch at ~line 137 to map `exit_code < 0` to `"oom_killed"` (`-9`) or `"sandbox_signaled"` (others) | FR-001, FR-005 |
| `agent/src/discogs_agent/tools/chart_validator.py` | Add branch for `exception_type == "oom_killed"` that emits a single named `ValidationError(rule="oom_killed", ...)` instead of the legacy three-error layering | FR-002 |
| `agent/src/discogs_agent/graph/nodes/response_synthesizer.py` | Extend `_build_result_block` with an `elif` branch that detects `oom_killed` in `validation_result.errors[]` and appends the diagnostic hint from R3 | FR-003 |
| `agent/src/discogs_agent/duckdb_layer/schema.py` | Replace `_DOMAIN_GLOSSARY` entry #3 with the R5 wording | FR-006, FR-007 |
| `agent/src/discogs_agent/prompts/code_generator.md` | Replace the "Critical rule for counting releases" bullets with the R6 wording | FR-008 |
| `agent/src/discogs_agent/prompts/repair_code.md` | Replace the Critical-rules bullet at lines 37–42 with the R6 wording | FR-009 |
| `agent/tests/integration/golden/schema_context_block.txt` | Regenerate to match the new `_DOMAIN_GLOSSARY` entry #3 | FR-010 |
| `agent/tests/unit/test_sandbox_signal_mapping.py` | New test module per R8 | FR-001 (test side) |
| `agent/tests/unit/test_chart_validator_oom_rule.py` | New test module per R8 | FR-002 (test side) |
| `specs/008-agent-frontend-v1/contracts/curated-questions.md` | Replace Q1 description line per R7 | FR-011 |
| `specs/005-agent-schema-context/contracts/schema-context.md` | Replace glossary entry #3 in the rendered-block example to match R5 | FR-012 (via amendment-005) |
| `specs/004-agent-v1/contracts/code-generation.md` | Add two new rows to §3.4 failure-modes table + a new sub-section pointing to the taxonomy doc | FR-013 (via amendment-004) |
| `specs/013-filtered-aggregation-postmortem/contracts/sandbox-exception-taxonomy.md` | New canonical taxonomy document | FR-014 |
| `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md` | New future-spec pointer document | FR-015 |

14 file changes; 4 are new files (2 tests + 2 contract docs), 10 are edits to existing files.
