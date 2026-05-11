# Feature Specification: Filtered-aggregation postmortem — sandbox OOM observability + glossary follow-on to 012

**Feature Branch**: `013-filtered-aggregation-postmortem`
**Created**: 2026-05-10
**Status**: Draft
**Input**: User description: *"extend 012 with the previous context of the error in this conversation. The idea is to: 1. Close the Observability gap. 2. Fix Glossary to extend the limitation"*

## Context: what slipped past 012

Spec 012 (`catalog-aggregation-postmortem`) landed three concrete mitigations against the `release_unique_view`-induced OOM-kill class:

1. `"memory_limit": "1GB"` baked into the generated-code `duckdb.connect(...)` template (commit `0ae0662`).
2. `/tmp/duckdb` tmpfs raised to 6 GiB in `docker-compose.yml` (commit `4143afd`).
3. Schema-context glossary entry #3 rewritten + `code_generator.md` "Critical rule" + `repair_code.md` reminder, all steering the LLM away from `release_unique_view` **for catalog-wide aggregations** (commit `4143afd`).

012 also promised, in its US2 acceptance criteria (012/spec.md:44–48): *"When a query genuinely exhausts the sandbox's resources, the failure mode is observable: DuckDB raises a real `OutOfMemoryException` that the validator can extract … No more `exit_code=-9` with empty stderr."*

On 2026-05-10 (post-012), run `b809ca52-12bc-4268-99d4-7603a5d0ecdd` failed exactly the way 012 promised it would not. User query: *"what is the work of Depeche Mode that has more versions?"* The LLM generated:

```sql
WITH depeche_mode_releases AS (
    SELECT mf.title, COUNT(DISTINCT rv.release_id) AS version_count
    FROM master_fact mf
    JOIN release_unique_view rv ON mf.master_id = rv.master_id
    JOIN release_artist_bridge rab ON rv.release_id = rab.release_id
    WHERE rab.artist_name = 'Depeche Mode'
    GROUP BY mf.title
)
SELECT title, version_count FROM depeche_mode_releases
ORDER BY version_count DESC LIMIT 1
```

`sql_safety_checker` passed it (EXPLAIN plan was valid). `sandbox_executor` reported:

```json
{ "exit_code": -9, "stderr": "", "stdout": "", "duration_ms": 7999,
  "exception_type": "nonzero_exit", "exception_message": "exit_code=-9" }
```

`chart_validator` produced three layered generic errors (`nonzero_exit`, `exception_raised`, `result_missing`). `run.errors[]` was empty. The user got the canned `"I generated code but couldn't produce a valid chart after retrying. Try rephrasing your question."` Triaging this required correlating `exit_code: -9` + empty stderr + ~8 s duration manually to infer "kernel cgroup OOM-killer," because:

- DuckDB's `memory_limit` only governs DuckDB-internal heap. Materializing `release_unique_view` (`SELECT DISTINCT` over ~33 columns of ~19M `release_fact` rows) pinned **tmpfs spill + Arrow conversion + Plotly-side buffers** in process-RSS terms, not DuckDB-heap terms.
- The Depeche Mode predicate sits on `release_artist_bridge`, joined two hops away. DuckDB cannot push it through the view's `SELECT DISTINCT`, so the view materializes fully before the predicate prunes.
- The 1 GiB cgroup limit therefore got hit by RSS, the kernel reaped the largest child (the sandbox subprocess) with SIGKILL, the harness saw `returncode = -9`, and 012's planned `OutOfMemoryException` path was never reached.

Two distinct gaps caused this incident to be **silent-ish** rather than diagnosable:

1. **Glossary loophole**: 012's rewrite still says *"DO NOT use release_unique_view for **catalog-wide aggregations**"*. The LLM read "catalog-wide" as "no WHERE clause," reasoned that a single-artist filter is *not* catalog-wide, and used the view anyway. The filter doesn't matter — the view materializes the same way regardless.
2. **Observability collapse**: the runtime's `exception_type: "nonzero_exit"` says nothing the operator couldn't already see from `exit_code: -9`. The kernel OOM-killer's signature (negative exit code, empty stderr, sub-timeout duration) was never named by the agent itself.

This spec closes both gaps as a 012 follow-on.

### Concurrent clarification: what `release_unique_view` is actually for

Investigation during 013's drafting surfaced a related framing issue worth recording. The ETL contract (`specs/001-discogs-etl/contracts/duckdb-schema.md:29`) describes `release_unique_view` as *"One row per release. Used for unique counts."* — implying the view is the canonical surface for catalog-grain queries. In practice, the view's definition (`SELECT DISTINCT (~33 columns) FROM release_fact`) forces a full materialization on every query and is **strictly more expensive** than the `COUNT(DISTINCT release_id) FROM release_fact GROUP BY X` idiom for count-shaped questions. The view earns its keep only in three narrow cases:

1. **Spot-check by release literal** (`WHERE release_id = N`). Tiny, fast, the only unambiguously safe usage today.
2. **SUM / AVG / MIN / MAX of release-grain numerics** (e.g., "average track_count per decade"). Aggregating on `release_fact` gives style-weighted answers (wrong); aggregating on the view gives the right answer but typically OOMs at catalog scale. There is no cheap path for this class of question on the current data shape.
3. **Existence/boolean filters at release grain** (e.g., "releases with vinyl from Germany"). Same trade-off: correct on the view, planner-dependent in practice.

For count-shaped questions including Q1 (*"Show releases by decade"*), `COUNT(DISTINCT release_id) FROM release_fact GROUP BY X` is strictly preferable and the agent already (post-012) reaches for it correctly. The `008/contracts/curated-questions.md:18` description claiming Q1 "uses release_unique_view" is stale documentation reflecting 001's intent, not the agent's actual (correct) behavior — 013 fixes that line as a side-cleanup.

The conceptual fix to the view's value proposition — rewriting its ETL materialization so it stops being a `SELECT DISTINCT` over 33 columns — is **out of scope for 013** and is being opened as a future ETL-component spec (provisional name: `014-release-unique-view-materialization` or similar). 013's glossary tightening is a workaround until that lands; if/when it does, the glossary can be loosened again to reflect the view earning its keep across all three load-bearing cases. 013 explicitly does not commit any ETL changes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Sandbox OOM-kills become a first-class observable signal (Priority: P1)

When the kernel's cgroup OOM-killer reaps the sandbox subprocess with SIGKILL, the agent's run record, validator output, and final response **name the cause** ("OOM-kill") instead of forwarding an opaque `nonzero_exit / exit_code=-9` triplet. An operator triaging a failed run from logs alone can identify "this was OOM" in one look, not five.

**Why this priority**: 012's US2 already promised this and didn't deliver it. The Depeche Mode failure proves the observability collapse leaks all the way to the user surface — the canned retry message tells the user nothing about what to try next, and the persisted run record forces a multi-step inference for the operator. Without this, future incidents of the same class will be just as opaque, regardless of whether US2 (glossary) bites.

**Independent Test**: Trigger any sandbox subprocess SIGKILL that is **not** harness-initiated (e.g., a deliberately memory-heavy query, or a stub that forces a cgroup breach). Inspect the resulting `agent_tool_calls.output_json` row for `sandbox_executor`: it MUST report `exception_type` set to a value distinguishable from both `"timeout"` and the legacy `"nonzero_exit"` (e.g., `"oom_killed"` or `"sandbox_signaled"`). The matching `chart_validator` row MUST emit a single named violation rule for this case rather than the legacy three-error pile. The `agent_runs.final_response` for this run MUST contain a phrase about resource limits rather than the generic "try rephrasing your question."

**Acceptance Scenarios**:

1. **Given** a query whose sandboxed execution is SIGKILL'd by the kernel cgroup OOM-killer, **When** the agent finishes the run, **Then** `sandbox_executor.output_json.exception_type` is the new named value (not `"nonzero_exit"`), `chart_validator.output_json.errors[]` contains exactly one rule that names the OOM case, and `final_response` includes wording that points the user at "memory pressure / try a narrower question" rather than the generic retry-failure copy.
2. **Given** a query whose sandboxed execution times out via the harness's own timeout path, **When** the agent finishes the run, **Then** `exception_type` remains `"timeout"` (no regression — the existing harness timeout label is preserved verbatim).
3. **Given** a query that fails for any non-signal reason (a legitimate Python exception inside the sandbox, e.g., a DuckDB `BinderError`, a Python `KeyError`), **When** the agent finishes the run, **Then** `exception_type` reflects the underlying cause (existing behavior) and is NOT relabeled as OOM.

---

### User Story 2 — `release_unique_view` is blocked in joins/group-bys regardless of filters (Priority: P1)

The glossary entry #3 in the rendered schema-context block (and its mirrors in `code_generator.md` + `repair_code.md`) MUST forbid `release_unique_view` in any `JOIN` or `GROUP BY`, not only in catalog-wide aggregations. The carve-out for single-release spot-checks (`WHERE release_id = <literal>`) remains. After this change, the LLM no longer has a "but my query is filtered, so it's fine" loophole.

**Why this priority**: tied with US1. The Depeche Mode case proves the current wording leaks. Closing the loophole is a one-line text change in the renderer plus mirrored edits in two prompts; it costs nothing and prevents the next instance of this same incident class. P1 because the alternative — relying solely on US1 observability — leaves a known recurring failure in place that the user experiences as "the agent can't answer my question," which is a Demo Day blocker.

**Independent Test**: Run the question *"what is the work of Depeche Mode that has more versions?"* and four other single-artist version-spread questions ("how many versions of Pink Floyd's Dark Side of the Moon exist," etc.) through the post-fix agent. Inspect the generated SQL in each `agent_runs.generated_sql`: none of them references `release_unique_view` in a `JOIN` or `GROUP BY`. The legitimate spot-check form (`SELECT … FROM release_unique_view WHERE release_id = N`) MUST still be permitted; verify by running a spot-check question or by inspecting the rendered glossary for the carve-out clause.

**Acceptance Scenarios**:

1. **Given** the Depeche Mode question above, **When** the agent runs end-to-end, **Then** the generated SQL counts versions via `release_fact` + `release_artist_bridge` (or directly via `master_fact.release_count` joined to the artist-bridge semi-join), with no `release_unique_view` appearing in a JOIN or GROUP BY.
2. **Given** a single-release spot-check question (e.g., *"show me release_id 12345"*), **When** the agent runs end-to-end, **Then** generated SQL may freely use `release_unique_view WHERE release_id = 12345` — the carve-out is intact.
3. **Given** the rendered schema-context block emitted on any run, **When** an operator inspects glossary entry #3, **Then** the prohibition is phrased as a blanket ban on JOIN/GROUP BY usage (no "catalog-wide" qualifier), and the spot-check carve-out is explicit.

---

### Edge Cases

- **Signal other than SIGKILL**: if the sandbox subprocess dies of SIGSEGV (`-11`), SIGABRT (`-6`), or SIGTERM (`-15`), the new exception_type SHOULD distinguish these or, at minimum, group them under a generic `"sandbox_signaled"` umbrella with the signal number preserved in `exception_message`. SIGKILL specifically maps to the OOM-killer in this sandbox cgroup (the harness's own timeout path is the only other producer of `-9`, and it already sets `exception_type = "timeout"` before the catch-all branch fires — see `agent/src/discogs_agent/sandbox/runner.py:107`).
- **`release_unique_view` inside a CTE that is then joined**: the glossary text must bite on usage shape, not just literal surface position. E.g., `WITH v AS (SELECT * FROM release_unique_view WHERE …) SELECT … FROM v JOIN release_artist_bridge …` is functionally a JOIN against the view. The glossary wording must make this clear (the contractual fix is wording; any static enforcement is out of scope).
- **Repair loop carries OOM into the prompt**: when the new `oom_killed` exception is observed, the `repair_code.md` reminder SHOULD surface it to the LLM on retry with a message like "the previous attempt was OOM-killed by the kernel — pick a cheaper plan." Currently, repair gets only `exception_type = "nonzero_exit"` which is too generic to act on. Whether this changes the LLM's repair behavior is empirical; the spec only requires the signal to reach the prompt.
- **Existing curated runs**: the seven curated demo questions are already passing post-012. The glossary tightening from "catalog-wide" → "any JOIN or GROUP BY" MUST NOT regress them. Verify by re-running the curated set through the post-fix agent.
- **Generic non-OOM Python exceptions inside the sandbox**: the existing `exception_type` extraction path (parsing `_error` from the sandbox payload, see `sandbox/runner.py:129`) takes precedence over the new signal mapping. The new mapping only fires when `exception_type` is still `None` and `exit_code < 0` at the catch-all branch (`runner.py:137`).
- **Known unresolved gap**: catalog-scale SUM/AVG/MIN/MAX over release-grain numerics (e.g., "average track_count per decade") has no cheap path on the current data shape. On `release_fact` the answer is style-weighted (wrong); on `release_unique_view` the materialization OOMs. With 013's glossary tightening in force, the LLM will avoid the view, hit the correctness problem, possibly emit silently-wrong style-weighted numbers, OR — if it correctly identifies the trap and tries the view anyway — OOM. This class of question is expected to remain partially answerable until the future ETL follow-on lands. The user-facing OOM message from US1 is the safety net.

## Requirements *(mandatory)*

### Functional Requirements

**Observability (US1)**

- **FR-001**: `agent/src/discogs_agent/sandbox/runner.py` MUST distinguish "harness timeout SIGKILL" (already labeled `"timeout"`, preserved) from "external SIGKILL" (currently mislabeled `"nonzero_exit"`). The fallthrough branch at the existing `if exit_code != 0 and exception_type is None` check MUST inspect the sign/value of `exit_code`: if `exit_code < 0`, set `exception_type` to a signal-aware named value (e.g., `"oom_killed"` for `-9`, `"sandbox_signaled"` for other negatives with signal number in `exception_message`).
- **FR-002**: `agent/src/discogs_agent/tools/chart_validator.py` MUST translate the new `exception_type` into a single named `ValidationError` rule (e.g., `rule="oom_killed"`) rather than the current three-error layering (`nonzero_exit` + `exception_raised` + `result_missing`). The legacy three-error path remains for genuinely unknown failures.
- **FR-003**: The response synthesizer MUST produce a user-facing message that names "memory pressure" (or equivalent plain-English phrasing) when the validator's named rule is the OOM case. The exact copy is not normative; the requirement is that the user gets a hint they can act on (e.g., "narrow your question to a single artist or year") instead of "Try rephrasing your question." This requirement applies only to the OOM rule, not the umbrella `sandbox_signaled` case (which retains the generic message).
- **FR-004**: When the agent enters its retry/repair path on an OOM-killed run, the repair prompt provided to the LLM MUST include the named cause in the error context, not the legacy `"exit_code=-9"` string. (Implementation note: this requires plumbing the new `exception_type` into whatever the repair prompt assembler reads; the spec does not dictate the variable name.)
- **FR-005**: The new exception_type taxonomy MUST be deterministic — the same `(exit_code, harness_timeout_fired)` tuple always produces the same `exception_type` value. No randomness, no LLM in the loop.

**Glossary tightening (US2)**

- **FR-006**: `_DOMAIN_GLOSSARY` entry #3 in `agent/src/discogs_agent/duckdb_layer/schema.py` MUST be rewritten so the prohibition on `release_unique_view` is unconditional in JOIN or GROUP BY contexts. The qualifier "for catalog-wide aggregations" MUST be removed or replaced with a non-restrictive phrasing (e.g., "in any JOIN or GROUP BY, regardless of WHERE filters").
- **FR-007**: The carve-out for spot-check queries (`WHERE release_id = <literal>`) on `release_unique_view` MUST be preserved verbatim.
- **FR-008**: The mirroring "Critical rule for counting releases" in `agent/src/discogs_agent/prompts/code_generator.md` MUST match the new glossary wording (no "catalog-wide" qualifier, blanket ban on JOIN/GROUP BY usage).
- **FR-009**: The mirroring reminder in `agent/src/discogs_agent/prompts/repair_code.md` MUST match the new glossary wording.
- **FR-010**: The integration-test golden snapshot at `agent/tests/integration/golden/schema_context_block.txt` MUST be regenerated to lock the new wording. The associated unit test `test_schema_context_glossary_contains_style_vs_genre_rule` MUST still pass (its keyword assertions on `primary_genre`, `style`, `decade`, `year` survive the rewrite).
- **FR-011**: The description line for Q1 in `specs/008-agent-frontend-v1/contracts/curated-questions.md:18` (currently "Basic decade-grain trend using release_unique_view") MUST be updated to match operational reality — the agent computes Q1's answer via `COUNT(DISTINCT release_id) FROM release_fact GROUP BY decade`, not via the view. New wording is descriptive only; this is a documentation cleanup with no test impact.

**Contract amendments**

- **FR-012**: `specs/005-agent-schema-context/contracts/schema-context.md` glossary entry #3 example block MUST be re-amended (second time, after 012's first amendment) to reflect the tightened wording. The amendment lives in this feature's `contracts/amendment-005-schema-context.md`.
- **FR-013**: `specs/004-agent-v1/contracts/code-generation.md` "Critical rule" section MUST be updated to track the new code_generator.md prose. The amendment lives in this feature's `contracts/amendment-004-code-generation.md`.
- **FR-014**: A new contract document under this feature's `contracts/` directory MUST define the sandbox `exception_type` taxonomy normatively: the set of allowed values, which exit-code conditions produce each, and which downstream validator rules each maps to. (The pre-013 taxonomy was implicit in the code; making it contractual is a 012-spirit back-fill.)
- **FR-015**: A future-spec pointer document under this feature's `contracts/` directory MUST record the ETL-side follow-on: rewriting `release_unique_view`'s materialization so the view stops being a `SELECT DISTINCT` over 33 columns. The document captures the intent; the implementation belongs to a separate ETL-component spec (provisional `014-release-unique-view-materialization`) and is NOT delivered by 013.

### Key Entities

- **`SandboxOutcome.exception_type`** (existing dataclass field at `agent/src/discogs_agent/sandbox/runner.py:37`) — taxonomy expands from `{None, "timeout", "parse_failed", "no_result", "nonzero_exit", <python-side _error string>}` to additionally include `"oom_killed"` (and optionally a generic `"sandbox_signaled"` for non-SIGKILL signals). The contract document under this feature's `contracts/` directory pins the canonical set.
- **`ValidationError`** (existing, emitted by `chart_validator.py`) — gains a new `rule` value matching the new exception_type. Legacy rules (`nonzero_exit`, `exception_raised`, `result_missing`) remain for genuine unknown cases; the OOM path no longer triggers them.
- **Glossary entry #3** (existing, lives in `_DOMAIN_GLOSSARY` and rendered into every LLM-facing schema-context block) — wording changes to remove the "catalog-wide" qualifier.
- **Repair prompt context** (existing, assembled when retry_count > 0) — gains the new `exception_type` as input so the LLM can see "the previous attempt was OOM-killed" instead of "exit_code=-9".
- **`agent_runs.final_response`** (existing Postgres column) — observed value changes for OOM-killed runs to include a memory-pressure hint.
- **Q1 description** (existing, `008/contracts/curated-questions.md:18`) — string changes to reflect post-012 agent behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of sandbox SIGKILL events that are not the harness's own timeout path, `agent_tool_calls.output_json.exception_type` for the `sandbox_executor` row contains the new named value (`oom_killed` or analogous), not `"nonzero_exit"`. Verifiable by replaying the Depeche Mode run (`b809ca52-12bc-4268-99d4-7603a5d0ecdd`) on the post-013 codebase or by inducing an OOM via a probe query.
- **SC-002**: The Depeche Mode question — *"what is the work of Depeche Mode that has more versions?"* — produces a successful chart on the post-013 codebase. Verifiable by running it through the agent end-to-end and inspecting `agent_runs.status == "succeeded"`.
- **SC-003**: For a manually constructed set of at least five single-artist "how many versions" / "which work has most versions" questions (Depeche Mode, Pink Floyd, The Beatles, Daft Punk, Aphex Twin), the generated SQL inspected in `agent_runs.generated_sql` contains zero occurrences of `release_unique_view` in JOIN or GROUP BY contexts. The set is small (five) because it's a regression-coverage probe, not a benchmark.
- **SC-004**: The seven curated demo questions from `specs/008-agent-frontend-v1/contracts/curated-questions.md` continue to pass on the post-013 codebase (no regressions from the glossary rewrite or the sandbox runner change).
- **SC-005**: Operator triage time on a fresh OOM-killed run drops to "single inspection step" — i.e., the named `exception_type` value alone identifies the failure class without requiring correlation with `exit_code`, `stderr`, or `duration_ms`. Verifiable by code review of the runner change + manual replay.
- **SC-006**: User-facing `final_response` for an OOM-killed run contains language about memory or query cost (e.g., contains one of `"memory"`, `"too heavy"`, `"narrow your question"`, `"reduce scope"`). Verifiable by inducing an OOM and reading the persisted final_response.
- **SC-007**: The integration golden `schema_context_block.txt` and the `code_generator.md` + `repair_code.md` prompt files all share byte-equivalent canonical wording for the new prohibition (verifiable by grep for `release_unique_view` across the three files producing semantically identical sentences).
- **SC-008**: The Q1 description line in `008/contracts/curated-questions.md` no longer claims the answer "uses release_unique_view" — verifiable by `grep -n release_unique_view specs/008-agent-frontend-v1/contracts/curated-questions.md` returning no match in the Q1 section.

## Assumptions

- **No infra changes**: the cgroup memory limit, sandbox CPU caps, tmpfs size, and DuckDB `memory_limit` settings from 012 remain at their current values. 013 is observability + steering work, not capacity work.
- **No ETL-side fix inside 013**: rewriting `release_unique_view` from `SELECT DISTINCT` to a properly materialized form remains deferred to a future ETL-component spec (provisional name `014-release-unique-view-materialization`). 013 documents that future work via FR-015 but does NOT deliver it. If/when the ETL fix lands, 013's glossary tightening can be loosened in a subsequent amendment; until then, the carve-out for spot-checks is the only safe usage.
- **No `RLIMIT_AS` hardening**: deferred per 012 spec.md line 85. 013 makes the existing soft-OOM observable; defense-in-depth via address-space caps is a separate decision.
- **Constitution VII.b compliance**: the glossary lives in the dynamically-rendered `{schema_context_block}`, which is the legitimate channel for steering query-shape preferences. The mirrored prose in `code_generator.md` and `repair_code.md` continues to be "rules of thumb tied to prompts' roles," not schema content (the same carve-out 012 relied on).
- **Signal semantics**: `exit_code < 0` from `subprocess.Popen` means "killed by signal `-exit_code`" on POSIX. `-9` = SIGKILL. In the sandbox cgroup, SIGKILL produced by anyone other than the harness's own timeout watchdog is the kernel OOM-killer in practice — there is no other agent in the system with permission to signal the subprocess. If a future change adds another SIGKILL source (e.g., a manual `docker kill` during testing), the `oom_killed` label may misattribute briefly; that's an acceptable false-positive given operator context.
- **No LLM retraining or fine-tune**: behavior change comes from prompt wording + repair-context plumbing, nothing else.
- **SUM/AVG-over-release-numerics remains partially unanswerable until 014 lands**: 013 acknowledges this gap explicitly in its Edge Cases section rather than masking it. The user-facing OOM message from US1 is the safety net when the LLM chooses the view anyway.

## Out of Scope

- **Architectural rewrite of `release_unique_view`** — deferred to a future ETL-component spec (provisional `014-release-unique-view-materialization`). FR-015 records the pointer; the work itself lives in the new spec.
- **`RLIMIT_AS` sandbox hardening** — deferred per 012.
- **Quantitative benchmarking** of how often the glossary tightening prevents OOM in the wild — this is a wording change validated by spot-check questions, not a measured-uplift study.
- **Backfill of historical `agent_runs` rows** — old runs persisted under the legacy `nonzero_exit` label stay as-is. The new taxonomy applies prospectively.
- **Refactoring the three-error layering in chart_validator for non-OOM failures** — only the OOM path is collapsed into a single rule; the legacy layering remains for everything else.
- **Spec 008 frontend wiring** — the frontend already renders whatever `final_response` and the error envelope contain. No frontend changes are required by this feature; the improvement is automatic when the backend changes ship.
- **Resolving the SUM/AVG-over-release-numerics correctness/performance gap** — this lands with 014, not 013.
- **Amending `001/contracts/duckdb-schema.md`** — its description of `release_unique_view` as the surface for unique counts remains accurate to ETL output shape; the operational reality (it's too expensive to use for most catalog-wide queries) is captured in the agent-side glossary instead.

## Dependencies

- **`agent/src/discogs_agent/sandbox/runner.py`** — the exception_type fallthrough branch (line 137) is the surgical site for FR-001.
- **`agent/src/discogs_agent/tools/chart_validator.py`** — the `exit_code != 0` and `exception_type` blocks (lines 58–69) are the surgical site for FR-002.
- **`agent/src/discogs_agent/duckdb_layer/schema.py`** — `_DOMAIN_GLOSSARY` entry #3 is the surgical site for FR-006.
- **`agent/src/discogs_agent/prompts/code_generator.md`** — "Critical rule for counting releases" section (lines 6–17 in the current version) is the surgical site for FR-008.
- **`agent/src/discogs_agent/prompts/repair_code.md`** — the matching reminder is the surgical site for FR-009.
- **`agent/tests/integration/golden/schema_context_block.txt`** — must be regenerated as part of FR-010.
- **`specs/008-agent-frontend-v1/contracts/curated-questions.md:18`** — the Q1 description line is the surgical site for FR-011.
- **Predecessor**: this feature explicitly extends 012-catalog-aggregation-postmortem. Both amendments produced by 013 are *second-round* amendments to the same target contracts that 012 already touched (`004/contracts/code-generation.md`, `005/contracts/schema-context.md`).
- **Successor (provisional)**: `014-release-unique-view-materialization` — ETL-side rewrite of the view so it stops being a `SELECT DISTINCT` over 33 columns. Not delivered by 013; only pointed at via FR-015.
- **No constitution amendment**: 013 stays inside Principle VII.b's existing carve-out for prompts-as-rules-of-thumb and the rendered-block-only schema-info channel. No new principles required.
