# Amendment to `005/contracts/schema-context.md` — cross-grain traversal hints (third-round rewrite)

**Source feature**: `014-cross-grain-join-postmortem`
**Target file**: `specs/005-agent-schema-context/contracts/schema-context.md` (cross-grain traversal hints normative section + example block)
**Predecessor amendments**:
- 009-schema-context-join-graph (first round — introduced the cross-grain hint and the forbidden-joins list)
- 013-filtered-aggregation-postmortem (second round — glossary entry #3 tightened, which inadvertently created the contradiction this amendment closes)

This is the third-round rewrite of the cross-grain traversal hint section. The forbidden-joins section (introduced by 009) is unchanged — see this feature's `amendment-009-cross-grain-hint.md` for that supersession note.

---

## Replacement: the "Cross-grain traversal hints" sub-block in the example

The current example block at `005/contracts/schema-context.md` lines around 245–256 (post-009 amendment) reads:

```markdown
Cross-grain traversal hints:
- master_id and release_id are DIFFERENT identifier namespaces. They
  cannot be compared to each other.
- To go from master_fact to artists or labels, traverse a release-grain
  table: master_fact -> release_unique_view (on master_id) ->
  release_artist_bridge (on release_id).
- Prefer release_unique_view (one row per release) over release_fact for
  cross-grain joins; release_fact is row-multiplied by style and may
  inflate counts.
- Bridges are NOT unique on release_id — one row per (release × artist)
  in release_artist_bridge, one row per (release × label) in
  release_label_bridge.
```

Replace it with:

```markdown
Cross-grain traversal hints:
- master_id and release_id are DIFFERENT identifier namespaces. They
  cannot be compared to each other.
- To go from master_fact to artists or labels, traverse via release_fact:
    master_fact -> release_fact (on master_id) ->
    release_artist_bridge (on release_id)
  Use COUNT(DISTINCT release_fact.master_id) for "works per X" and
  COUNT(DISTINCT release_fact.release_id) for "releases per X".
  release_fact has grain release × style, so naive COUNT(*) double-counts.
- release_unique_view is NOT a usable traversal surface — it's only safe
  for single-release spot-checks (see glossary entry #3). Always traverse
  through release_fact for cross-grain joins.
- Bridges are NOT unique on release_id — one row per (release × artist)
  in release_artist_bridge, one row per (release × label) in
  release_label_bridge.
```

The wording in the deployed renderer (`agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph`, lines 224–246 post-014) MUST be byte-equivalent to this replacement.

---

## Three deltas from the 009 wording

1. **Worked-example traversal table**: `release_unique_view` → `release_fact`. Pre-013, `release_unique_view` was the recommended traversal surface. Post-013, the view is forbidden in JOIN/GROUP BY (glossary entry #3); the hint was the contradicting recommendation that the LLM resolved by inventing a forbidden join. 014 closes the contradiction at its source.
2. **New COUNT-pattern note** added immediately under the worked example. Tells the LLM both `master_id` and `release_id` `COUNT(DISTINCT)` patterns and warns about the release × style multiplication. This is the information the LLM needs to write correct release-fact-based aggregations without re-discovering it for each question.
3. **Positive prohibition replaces the legacy "Prefer release_unique_view" line**. The legacy line directly contradicted glossary entry #3; deleting it is necessary but not sufficient — the LLM may revert to the view by default if not actively steered away. The new line says `"release_unique_view is NOT a usable traversal surface"` with an explicit cross-reference to glossary entry #3.

---

## Why this matters

013 demonstrated that the LLM resolves prompt contradictions by inventing shortcuts. The Depeche Mode case (013's trigger) was caught at OOM-time because the LLM tried to USE the forbidden surface. The cross-grain-join case (014's trigger, run `2557c2ce-...`) was NOT caught at any runtime because the LLM tried to AVOID the forbidden surface by inventing a different forbidden shape — and DuckDB happily executed the syntactically-valid (but semantically-meaningless) query.

The fix is to give the LLM ONE consistent recommended path. After 014, both the cross-grain hint and glossary entry #3 agree: `release_fact` is the traversal surface; `release_unique_view` is for spot-checks only.

---

## Updated normative requirements section

The pre-014 `005/contracts/schema-context.md` normative requirements section (around lines 245–256) reads:

```markdown
2. **Cross-grain traversal hints** — at minimum:
   - A line stating that `master_id` and `release_id` are different identifier namespaces and cannot be compared to each other (master-side, conditional on `has_master_fact`).
   - A worked example showing the master → release → bridge traversal (master-side, conditional).
   - A note preferring `release_unique_view` over `release_fact` for cross-grain joins (because `release_fact` is row-multiplied by style).
   - A note that bridges are NOT unique on `release_id` (one row per release × artist or release × label).
```

Replace it with:

```markdown
2. **Cross-grain traversal hints** — at minimum:
   - A line stating that `master_id` and `release_id` are different identifier namespaces and cannot be compared to each other (master-side, conditional on `has_master_fact`).
   - A worked example showing the master → release → bridge traversal **via release_fact** (master-side, conditional on `has_master_fact`).
   - A COUNT-pattern note explaining that `COUNT(DISTINCT release_fact.master_id)` and `COUNT(DISTINCT release_fact.release_id)` collapse the release × style multiplication correctly.
   - A positive prohibition stating that `release_unique_view` is NOT a usable traversal surface, with a cross-reference to glossary entry #3 (which forbids the view in JOIN/GROUP BY per 013).
   - A note that bridges are NOT unique on `release_id` (one row per release × artist or release × label).
```

The pre-014 third bullet ("note preferring release_unique_view over release_fact") is **deleted**. Pre-014 fourth bullet ("bridges are NOT unique on release_id") is renumbered as the fifth bullet but otherwise unchanged.

---

## Constitution VII.b compliance

The replacement entry lives in the dynamically-rendered `{schema_context_block}` produced by `_render_join_graph`. Per Constitution VII.b ("schema info comes ONLY via the rendered block"), this is the legitimate channel for steering the LLM's query-shape preferences. No static schema prose is added to any prompt template.

The cross-grain hint is *catalog-fact* description (which tables exist, what their grains are, how to traverse between them). It belongs in the rendered block, not in a prompt's rule-of-thumb section.

---

## Verification

The deployed renderer at `agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph` MUST emit this exact wording after FR-001 through FR-005 land. The golden snapshot at `agent/tests/integration/golden/schema_context_block.txt` MUST be regenerated (FR-006) on the same commit. The integration test `test_rendered_block_matches_golden` locks the deployed wording.

The unit tests in `agent/tests/unit/test_schema_context.py` MUST be updated (FR-007) to assert on the new phrases (`"master_fact -> release_fact (on master_id)"` and `"release_unique_view is NOT a usable traversal surface"`).

---

## Implementation pointer

Implementation lands as part of 014:

- `agent/src/discogs_agent/duckdb_layer/schema.py` `_render_join_graph` lines 224–246 — replaced.
- `agent/tests/integration/golden/schema_context_block.txt` — regenerated.
- `agent/tests/unit/test_schema_context.py` — phrase assertions updated.
- This contract example block in `005/contracts/schema-context.md` — replaced per this amendment.
- This contract's normative requirements section — replaced per this amendment.
