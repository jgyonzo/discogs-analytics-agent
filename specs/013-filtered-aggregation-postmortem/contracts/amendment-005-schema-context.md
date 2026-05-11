# Amendment to `005/contracts/schema-context.md` — glossary entry #3 (second-round rewrite)

**Source feature**: `013-filtered-aggregation-postmortem`
**Target file**: `specs/005-agent-schema-context/contracts/schema-context.md`
**Predecessor amendment**: `specs/012-catalog-aggregation-postmortem/contracts/amendment-005-schema-context.md` (first-round rewrite)
**Update**: replace the example block's glossary entry #3 with the new wording. The schema-context renderer in `agent/src/discogs_agent/duckdb_layer/schema.py` `_DOMAIN_GLOSSARY` is the deployed source of truth; this amendment makes the contract document match the code change landing under 013.

---

## Replacement: glossary entry #3 in the example block

The current entry #3 (post-012, around lines 136–148 of `005/contracts/schema-context.md`'s example block) reads:

```markdown
3) release_fact has grain release × style. For counts of unique
   releases, use `SELECT X, COUNT(DISTINCT release_id) FROM
   release_fact GROUP BY X` — this only tracks per-X distinct
   sets and is cheap. DO NOT use release_unique_view for
   catalog-wide aggregations: the view is defined as
   `SELECT DISTINCT (~33 columns) FROM release_fact` and forces
   DuckDB to materialize the entire deduplicated set (~19M rows
   × 33 cols), which spills GBs of temp even for trivial
   GROUP BYs. release_unique_view is fine for spot-check queries
   against a single release (e.g., `WHERE release_id = N`),
   but never for catalog-wide GROUP BYs. Never use `COUNT(*)
   FROM release_fact` for release counts (it counts release ×
   style rows, not releases).
```

Replace it with:

```markdown
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

The wording in the renderer's `_DOMAIN_GLOSSARY` MUST be byte-equivalent to this replacement; the contract example is the human-facing canonical form.

---

## Three deltas from the 012 wording

1. **"for catalog-wide aggregations" → "in any JOIN or GROUP BY, regardless of WHERE filters"**
   Closes the loophole the Depeche Mode case exploited. The 012 phrasing let the LLM rationalize that a single-artist filter wasn't "catalog-wide," even though the view materializes identically regardless of the filter's selectivity.
2. **"spills GBs of temp even for trivial GROUP BYs" → "typically OOMs the sandbox even when the query has selective WHERE clauses on a joined table (the planner cannot push the predicate through the view's DISTINCT)"**
   Names the *actual* failure mechanism the user just hit. The previous wording suggested the failure was a slow-but-finite spill; the actual failure is an OOM-kill because predicate pushdown is blocked by the DISTINCT.
3. **"is fine for spot-check queries against a single release (e.g., `WHERE release_id = N`), but never for catalog-wide GROUP BYs" → "is ONLY safe for spot-check queries that filter directly on a single release literal (e.g., `SELECT * FROM release_unique_view WHERE release_id = N`)"**
   Tightens the carve-out from a permissive description ("is fine for X, but never for Y") to a positive specification ("is ONLY safe for X"). Easier for the LLM to apply.

---

## Why this matters

The 012 wording leaked because "catalog-wide" was an LLM-interpretable qualifier — the model decided what counted as "catalog-wide" using prose context, not query shape. The 013 wording bites on *query shape* instead: if your SQL has `JOIN release_unique_view` or `GROUP BY` after `FROM release_unique_view`, you must rewrite. The only acceptable shape is `SELECT … FROM release_unique_view WHERE release_id = <literal>`.

The added operational note (predicate pushdown is blocked by the DISTINCT) gives the LLM the *mechanistic* explanation it needs to apply the rule confidently to novel queries, not just the ones already memorized in the prompt.

---

## Constitution VII.b compliance

The replacement entry lives in the dynamically-rendered `{schema_context_block}`. Per Constitution VII.b ("schema info comes ONLY via the rendered block"), this is the legitimate channel for steering the LLM's query-shape preferences. No static schema prose was added to any prompt template.

The mirroring "Critical rule" in `code_generator.md` and the matching reminder in `repair_code.md` are **rules-of-thumb tied to the prompts' roles** (per VII.b's "What prompts MAY contain" carve-out), not catalog-fact descriptions. They reinforce the glossary without duplicating its schema content.

---

## Verification

The deployed renderer at `agent/src/discogs_agent/duckdb_layer/schema.py` (`_DOMAIN_GLOSSARY` entry #3) MUST emit this exact wording after FR-006 lands. The golden snapshot at `agent/tests/integration/golden/schema_context_block.txt` MUST be regenerated (FR-010) on the same commit. The integration test `test_rendered_block_matches_golden` locks the deployed wording.

The unit test `test_schema_context_glossary_contains_style_vs_genre_rule` asserts the glossary contains specific keywords (`primary_genre`, `style`, `decade`, `year`) — three of these (`primary_genre`, `style`, `decade`) appear in glossary entries #1, #2, #4 (unchanged); `style` ALSO appears in the rewritten entry #3 ("release × style"). All four keywords survive the rewrite.

---

## Implementation pointer

Implementation lands as part of 013:

- `agent/src/discogs_agent/duckdb_layer/schema.py` `_DOMAIN_GLOSSARY` entry #3 — replaced.
- `agent/tests/integration/golden/schema_context_block.txt` — regenerated.
- This contract example block in `005/contracts/schema-context.md` — replaced per this amendment.
