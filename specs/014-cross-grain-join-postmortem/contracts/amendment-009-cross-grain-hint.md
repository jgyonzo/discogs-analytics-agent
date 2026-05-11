# Supersession note: 009's `amendment-005-schema-context.md` — cross-grain hint section

**Source feature**: `014-cross-grain-join-postmortem`
**Target file**: `specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md`
**Scope**: cross-grain traversal hints sub-section only. The forbidden-joins sub-section (also introduced by 009) is unchanged and remains authoritative from 009 — 014 promotes it to runtime enforcement (`forbidden_join` rule in sql_safety_checker) but does not modify its rendered text.

This is a supersession note, not a full rewrite. The 009 amendment document remains valid for the forbidden-joins section + the join-edges section + the general structure. Only the cross-grain hints section is superseded.

---

## What 009's amendment-005 said about cross-grain hints (now superseded)

From `009/contracts/amendment-005-schema-context.md` lines 43–48:

> The "Cross-grain traversal hints" sub-block MUST contain at minimum:
> - A line stating that `master_id` and `release_id` are different identifier namespaces and cannot be compared to each other.
> - A worked example showing the master → release → bridge traversal (master-side; emitted only when `has_master_fact = true`).
> - A note preferring `release_unique_view` over `release_fact` for cross-grain joins (because `release_fact` is row-multiplied by style).
> - A note that bridges are NOT unique on `release_id` (one row per release × artist or release × label).

And from the example block at 009/amendment-005:113–118:

```
Cross-grain traversal hints:
- master_id and release_id are DIFFERENT identifier namespaces. They
  cannot be compared to each other.
- To go from master_fact to artists or labels, traverse a release-grain
  table: master_fact -> release_unique_view (on master_id) ->
  release_artist_bridge (on release_id).
```

---

## Why 014 supersedes the hint section

013-filtered-aggregation-postmortem (post-009) tightened glossary entry #3 to forbid `release_unique_view` in any JOIN or GROUP BY (regardless of WHERE filters). 009's cross-grain hint still recommended that exact path. The contradiction surfaced on 2026-05-10 in run `2557c2ce-21e2-4838-8790-d54528e8043c`: the LLM resolved the conflict by inventing a forbidden join (the first entry in 009's forbidden-joins list — `master_fact.master_id = release_artist_bridge.release_id`).

014 closes the contradiction by:

1. Replacing 009's traversal-via-release_unique_view recommendation with traversal-via-release_fact.
2. Adding a COUNT-pattern note explaining how to collapse the release × style multiplication correctly with `release_fact`.
3. Replacing 009's "prefer release_unique_view" line with a positive prohibition: "release_unique_view is NOT a usable traversal surface — see glossary entry #3."

The new normative text and example block are in this feature's `amendment-005-schema-context.md` (third-round rewrite of 005).

---

## What 009's amendment-005 retains as authoritative

Unchanged by 014:

- **The forbidden-joins section** (009/amendment-005:50–54 and 009/amendment-005:120–124 example block). The list of forbidden joins remains as 009 specified. 014 promotes this list from descriptive prose to runtime enforcement via `sql_safety_checker._FORBIDDEN_JOIN_PAIRS`, but the rendered text is identical.
- **The join-edges section** (009/amendment-005:35–41). Edges between allowlisted tables — unchanged.
- **The structure of the "Join graph" parent section** (009/amendment-005:25–32). Header, subsection order, conditional emission rules — unchanged.

---

## What this supersession document does NOT do

- It does NOT delete 009's amendment-005 from the spec tree. The document remains as historical record of 009's contribution. 014's spec tree contains the third-round rewrite alongside this supersession note.
- It does NOT modify the `specs/009-schema-context-join-graph/` directory contents (Constitution: predecessor specs' artifacts are frozen as historical record). All changes land in 014's spec tree.
- It does NOT change the rendered forbidden-joins text. Only the cross-grain hint section.

---

## Constitution compliance

Constitution Principle VI (Two Components, One Contract): the supersession is fully within the `agent/` component. The `005/contracts/schema-context.md` document itself is updated per `014/contracts/amendment-005-schema-context.md`; 009's amendment document is preserved as-is in 009's spec tree.

Constitution Principle VII.b (Prompt-authoring discipline): the cross-grain hint is catalog-fact description and belongs in the rendered block (which is the legitimate channel). 014 updates the renderer; the prompts themselves are not modified.

---

## Implementation pointer

Implementation lands as part of 014:

- `agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph` lines 224–246 — replaced with the new wording. The lines 249–262 (forbidden-joins sub-block) — unchanged.
- `agent/src/discogs_agent/tools/sql_safety_checker.py` — gains `_FORBIDDEN_JOIN_PAIRS` constant and `_scan_forbidden_joins` pass. This is the runtime enforcement layer that 014 introduces; the rendered list it enforces is unchanged from 009.
- `specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md` itself — NOT modified. This supersession note in 014's spec tree is the canonical record of what changes.
