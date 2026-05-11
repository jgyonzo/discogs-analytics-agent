# Renumbering: 013's successor pointer (014 → 015)

**Source feature**: `014-cross-grain-join-postmortem`
**Target file**: `specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md`
**Operation**: rename + content edit.
**Spec FR**: FR-018.

This document records the renumbering admin task that 014 performs as part of its scope. 013 reserved the provisional spec number `014-release-unique-view-materialization` for the deferred ETL-component fix (rewriting `release_unique_view`'s `SELECT DISTINCT (~33 cols)` materialization). On 2026-05-10, the cross-grain-join postmortem became the actual occupant of 014, so the ETL follow-on bumps to 015.

---

## Step 1: File rename

```sh
git mv specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md \
        specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md
```

`git mv` (not `rm + add`) preserves the file's history under `git blame`. The filename change is purely administrative — the content describes the same deferred ETL fix.

---

## Step 2: Content edits

Inside the renamed file, every occurrence of `014-release-unique-view-materialization` (the provisional ETL spec name) MUST be replaced with `015-release-unique-view-materialization`. Specific lines (post-013 baseline):

| Location | Pre-014 text | Post-014 text |
|---|---|---|
| Document title (line 1) | `# Successor pointer: future ETL-component spec (\`014-release-unique-view-materialization\`)` | `# Successor pointer: future ETL-component spec (\`015-release-unique-view-materialization\`)` |
| Provisional naming section (around line 121) | `Spec number: \`014-release-unique-view-materialization\` (provisional; ...)` | `Spec number: \`015-release-unique-view-materialization\` (provisional; ...)` |
| Acceptance criterion section | `When the benchmark passes, 013's glossary entry #3 SHOULD be loosened in a subsequent amendment` | unchanged |
| Component section | `Target component: \`etl/\`` | unchanged |

---

## Step 3: New historical-context note

Insert a new paragraph at the top of the renamed file, immediately after the document title and metadata block. Suggested wording:

```markdown
*Note: this document was originally drafted as `successor-014-pointer.md`
during 013's `/speckit-plan` phase, when "014" was the provisional spec
number for this deferred ETL fix. On 2026-05-10, the cross-grain-join
postmortem (`014-cross-grain-join-postmortem`) became the actual
occupant of 014, so the ETL follow-on was renumbered to "015" by
014's FR-018. See `specs/014-cross-grain-join-postmortem/contracts/renumbering-013-pointer.md`
for the renumbering record.*
```

---

## Why this matters

- **Greppability**: a future operator searching `git ls-files | grep successor-014` would find an orphan file pointing at a spec that doesn't match the filename. Renumbering aligns the filename with the referenced spec number.
- **Discoverability of provenance**: the historical-context note tells a future reader where the pre-014 history lives (in this 014/contracts/renumbering-013-pointer.md document) without forcing them to spelunk through commit history.
- **SDD discipline**: 013's spec called the ETL follow-on "014" provisionally. Once 014 was occupied by a different spec, the pointer needed correction. Doing the correction inside the spec that *took* 014 (rather than as a separate floating commit) keeps the SDD record self-contained.

---

## What this is NOT

- It is NOT a re-deferral of the ETL fix. The 015 work remains deferred under the same conditions 013 specified (open it when a real user question hits the SUM/AVG-over-release-numerics class and OOMs, or when an ETL maintenance sprint absorbs it). 014 only renumbers the pointer.
- It is NOT a modification of the deferred work's scope or acceptance criteria. The pointer's content (deferred problem, suggested implementation directions, acceptance criterion) is preserved verbatim. Only the spec number changes.
- It is NOT a constitutional concern. Constitution Principle VI's "predecessor specs' artifacts are frozen" guidance is about *substantive* content; an admin renumbering of a forward-looking pointer doc is housekeeping, not amendment.

---

## Verification

After the rename + content edits land:

```sh
# OLD path no longer exists
test ! -f specs/013-filtered-aggregation-postmortem/contracts/successor-014-pointer.md

# NEW path exists with the corrected spec number
grep -q "015-release-unique-view-materialization" \
  specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md

# Document title reflects the new number
grep -q "^# Successor pointer: future ETL-component spec.*015" \
  specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md

# Historical-context note is in place
grep -q "originally drafted as.*successor-014-pointer.md" \
  specs/013-filtered-aggregation-postmortem/contracts/successor-015-pointer.md
```

All four checks MUST pass on the post-014 codebase.

---

## Implementation pointer

The rename + content edits land in `014`'s implementation commit alongside the spec/code changes. There is no code change associated with this contract — it's pure documentation maintenance.
