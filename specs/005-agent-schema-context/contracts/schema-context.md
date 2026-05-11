# Contract: Enriched Schema Context

This contract pins the shape of the schema-context payload that
every prompt-rendering function receives. It supersedes (and is
backwards-compatible with) the implicit shape used in
`004-agent-v1`.

## Producer

`discogs_agent.duckdb_layer.schema.get_schema_context(duckdb_path)`
— extended; same signature; returns a richer `SchemaContext`
TypedDict.

## Consumers

- `discogs_agent.graph.nodes.router._render_prompt`
- `discogs_agent.graph.nodes.query_understanding._render_prompt`
- `discogs_agent.graph.nodes.code_generator._render_prompt` (and
  the repair variant)
- `discogs_agent.tools.query_classifier._render_prompt`
- `discogs_agent.tools.sql_safety_checker` (forbidden-table
  scan; uses only `tables` keys)

## Wire shape (in-process; not serialised over HTTP)

```python
{
  "tables": {
    "release_fact": [
      {"name": "release_id", "type": "BIGINT"},
      {"name": "style", "type": "VARCHAR"},
      ...
    ],
    "release_unique_view": [...],
    "release_artist_bridge": [...],
    "release_label_bridge": [...]
    # "master_fact" present iff the published catalog has it
  },

  "has_master_fact": false,
  "duckdb_path": "/data/published/duckdb/discogs.duckdb",
  "captured_at": "2026-05-01T12:00:00+00:00",
  "warnings": [],

  "sample_values": {
    "release_unique_view": {
      "primary_genre": [
        {"value": "Rock", "count": 5454580},
        ... 13 more ...
      ],
      "primary_format_group": [...],
      "decade": [{"value": 2010, "count": 6543210}, ...],
      "country": [... top-20 ...]
    },
    "release_fact": {
      "style": [
        {"value": "House", "count": 803_xxx},
        ... up to 50 ...
      ]
    }
  },

  "domain_glossary": [
    "primary_genre is the coarse bucket (Rock, Electronic, ...).
     style is the granular subgenre (Techno, House, ...). Filter
     by 'style' on release_fact for subgenre questions; filter
     by 'primary_genre' on release_unique_view only when the
     value literally appears in the primary_genre sample.",
    "For 'evolution / over time / trend' questions WITHOUT
     explicit yearly granularity, group by decade not year.
     Override only when the user says 'year', 'yearly', or
     'annual'.",
    "release_fact has grain release × style; counts of unique
     releases use COUNT(DISTINCT release_id) or
     release_unique_view."
  ],

  "published_run_id": "20260415-fullrun-001",
  "rendered_block": "<pre-rendered string interpolated into
                     prompts>",
  "rendered_token_count": 487
}
```

## Rendered block format (the string passed into prompts)

The pre-rendered block is what each prompt uses via a
`{schema_context_block}` placeholder. Plain text, ordered for
LLM-friendliness:

```text
Available tables (allowlist):

- release_fact (grain: release × style):
  release_id, master_id, title, year, decade, country, style,
  primary_genre, primary_format_group, has_vinyl, has_cd, ...

- release_unique_view (grain: one row per release):
  release_id, master_id, title, year, decade, country,
  primary_genre, primary_format_group, ...

- release_artist_bridge: release_id, artist_id, ...
- release_label_bridge: release_id, label_id, ...
- master_fact (grain: master release): master_id, title,
  main_release_id, year, decade, release_count, ...

Sample distinct values for low-cardinality columns:

- release_unique_view.primary_genre (14): Rock, Electronic,
  Pop, Jazz, Folk/World/Country, Classical, Hip Hop, Funk/Soul,
  Latin, Reggae, Non-Music, Stage & Screen, Blues, Children's,
  Brass & Military.

- release_unique_view.primary_format_group: Vinyl, CD, Digital,
  Cassette, Box Set, ...

- release_unique_view.decade: 1900, 1910, ..., 2020.

- release_unique_view.country (top-20 by release count): US, UK,
  DE, JP, FR, ...

- release_fact.style (top-50 by release count): House, Techno,
  Pop Rock, Ambient, Trance, Drum n Bass, Acid Jazz, ...

Join graph (foreign-key relationships between allowlisted tables):

Edges:
- release_fact.release_id  ↔  release_unique_view.release_id
- release_fact.release_id  ↔  release_artist_bridge.release_id
- release_fact.release_id  ↔  release_label_bridge.release_id
- release_unique_view.release_id  ↔  release_artist_bridge.release_id
- release_unique_view.release_id  ↔  release_label_bridge.release_id
- release_fact.master_id  ↔  master_fact.master_id
- release_unique_view.master_id  ↔  master_fact.master_id

Cross-grain traversal hints:
- master_id and release_id are DIFFERENT identifier namespaces.
  They cannot be compared to each other.
- To go from master_fact to artists or labels, traverse via
  release_fact:
    master_fact -> release_fact (on master_id) ->
    release_artist_bridge (on release_id)
  Use COUNT(DISTINCT release_fact.master_id) for "works per X"
  and COUNT(DISTINCT release_fact.release_id) for "releases per X".
  release_fact has grain release × style, so naive COUNT(*)
  double-counts.
- release_unique_view is NOT a usable traversal surface — it's
  only safe for single-release spot-checks (see glossary entry
  #3). Always traverse through release_fact for cross-grain joins.
- Bridges are NOT unique on release_id — one row per
  (release × artist) in release_artist_bridge, one row per
  (release × label) in release_label_bridge.

Forbidden joins (will return semantically wrong rows even if the
SQL runs):
- master_fact.master_id  =  release_artist_bridge.release_id
- master_fact.master_id  =  release_label_bridge.release_id
- master_fact.main_release_id  =  release_*_bridge.release_id

Domain glossary:

1) primary_genre is the coarse bucket (Rock, Electronic, ...).
   style is the granular subgenre (Techno, House, ...). Filter
   by 'style' on release_fact for subgenre questions; filter by
   'primary_genre' on release_unique_view only when the value
   literally appears in the primary_genre sample.

2) For "evolution / over time / trend" questions WITHOUT
   explicit yearly granularity, group by decade not year.
   Override only when the user says "year", "yearly", or
   "annual".

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
   *(Updated 2026-05-09 by `012-catalog-aggregation-postmortem`;
   tightened 2026-05-10 by `013-filtered-aggregation-postmortem`
   to close the "catalog-wide" loophole — see
   [013/contracts/amendment-005-schema-context.md](../../013-filtered-aggregation-postmortem/contracts/amendment-005-schema-context.md).)*

4) release_artist_bridge and release_label_bridge are NOT unique
   on release_id — one row per (release × artist) or
   (release × label). For "releases per artist" or "releases per
   label", GROUP BY the artist/label and use COUNT(DISTINCT
   release_id); naive COUNT(*) double-counts.
```

## Join graph

*Added 2026-05-07 by `009-schema-context-join-graph`. Closes the
silent wrong-answer class of bug where the LLM hallucinated joins
between unrelated identifier namespaces (e.g.,
`master_fact.master_id = release_artist_bridge.release_id` —
two different identifier spaces, both BIGINT, so the join compiled
and returned semantically wrong rows). The 003 contract has the
correct guidance ("Use `release_unique_view.master_id` for
release-grain joins") but Constitution VII.b explicitly forbids
embedding schema info in static prompt prose; the only legitimate
surface is the rendered block. This section makes that delivery
mechanical.*

The rendered block carries a "Join graph" section listing the
foreign-key relationships between allowlisted tables. The section
is derived from the published-DuckDB contracts
(`001-discogs-etl/contracts/duckdb-schema.md` and
`003-masters-artists/contracts/duckdb-schema.md`); the renderer
does NOT invent edges.

### Position in the rendered output

After the table/grain block and the sample-values block, BEFORE
the domain glossary. The order in the rendered output is:

1. Available tables (allowlist) + grains
2. (optional) `master_fact is NOT present in this catalog` line
3. Sample distinct values
4. **Join graph** ← this section
5. Domain glossary

### Required sub-blocks

The "Join graph" section MUST contain three sub-blocks, in order:

1. **Edges** — a flat list of foreign-key pairs in
   `table.column ↔ table.column` form. Edges that reference
   `master_fact` are emitted only when `has_master_fact = true`.
   Minimum edges (when all tables are present):

   - `release_fact.release_id ↔ release_unique_view.release_id`
   - `release_fact.release_id ↔ release_artist_bridge.release_id`
   - `release_fact.release_id ↔ release_label_bridge.release_id`
   - `release_unique_view.release_id ↔ release_artist_bridge.release_id`
   - `release_unique_view.release_id ↔ release_label_bridge.release_id`
   - `release_fact.master_id ↔ master_fact.master_id` (master-side, conditional)
   - `release_unique_view.master_id ↔ master_fact.master_id` (master-side, conditional)

2. **Cross-grain traversal hints** — at minimum:

   - A line stating that `master_id` and `release_id` are
     different identifier namespaces and cannot be compared to
     each other (master-side, conditional on `has_master_fact`).
   - A worked example showing the master → release → bridge
     traversal **via `release_fact`** (master-side, conditional
     on `has_master_fact`). *(Updated 2026-05-10 by
     `014-cross-grain-join-postmortem` — pre-014 this used
     `release_unique_view`, which 013's glossary entry #3
     forbids in any JOIN/GROUP BY. See
     [014/contracts/amendment-005-schema-context.md](../../014-cross-grain-join-postmortem/contracts/amendment-005-schema-context.md).)*
   - A COUNT-pattern note explaining that
     `COUNT(DISTINCT release_fact.master_id)` and
     `COUNT(DISTINCT release_fact.release_id)` collapse the
     release × style multiplication correctly.
   - A positive prohibition stating that `release_unique_view`
     is NOT a usable traversal surface, with a cross-reference
     to glossary entry #3 (which forbids the view in JOIN/GROUP
     BY per 013).
   - A note that bridges are NOT unique on `release_id` (one row
     per release × artist or release × label).

3. **Forbidden joins** — at minimum (when `has_master_fact = true`):

   - `master_fact.master_id = release_artist_bridge.release_id`
     (the canonical bug)
   - `master_fact.master_id = release_label_bridge.release_id`
     (the same class of error on the label side)
   - `master_fact.main_release_id = release_*_bridge.release_id`
     (a related plausible-but-wrong join — `main_release_id` IS
     a release_id but its use should be deliberate, not the
     default cross-grain path)

   When `has_master_fact = false`, the "Forbidden joins"
   sub-block MAY be omitted entirely (no master-side joins are
   reachable on a release-only catalog).

### Catalog-conditional rendering

- When `has_master_fact = false`, the renderer MUST omit all
  `master_fact`-referencing edges, the master-side traversal
  hint, and the master-side forbidden-join lines. It MAY still
  render the section with the release-side edges only.
- When the catalog has fewer than two allowlisted tables (a
  degenerate case never produced by a valid published DuckDB),
  the renderer MAY skip the section entirely.

### Token budget interaction

The "Join graph" section is rendered unconditionally within the
`_TOKEN_BUDGET` (1600 tokens post-`011-token-budget-recalibration`;
see "## Token budget" below for the recalibration history).
Empirically (April 2026 full catalog) the section adds ~300 tokens
(009/research originally estimated 220; reality is ~300 because
unicode arrows + traversal hints + master_fact column list run
longer than the estimate). If the rendered block exceeds the
budget, the truncation order in `_TRUNCATION_STEPS` MUST drop
sample values BEFORE any join-graph content. Join-graph content
is NOT eligible for truncation.

### Backwards compatibility

The `SchemaContext` TypedDict shape is unchanged by this
amendment. The new content is inside the existing `rendered_block`
string. Consumers that read only `tables`, `has_master_fact`,
`sample_values`, or `domain_glossary` continue to work without
modification.

## Token budget

`rendered_token_count` MUST be ≤ 1600. The producer computes it
using `tiktoken` (graceful fallback to `cl100k_base` if the
model alias isn't recognised).

### Recalibration history

- **Pre-009**: 1200 tokens. Sized against ~487 tokens for the
  full April 2026 catalog (tables + samples + glossary, no join
  graph).
- **Post-009**: still 1200, with the join-graph section adding
  an estimated ~220 tokens. Estimate was off — see below.
- **Post-011 (2026-05-08)**: raised to 1600 after production
  observation. The April 2026 full catalog rendered at 1295
  tokens before truncation and 1217 after both `_TRUNCATION_STEPS`
  fired (warning `schema_context_over_budget_after_truncation`).
  The 220-token estimate for the join graph in 009 turned out to
  be ~300 tokens in practice (unicode arrows + traversal hints +
  master_fact column list), and the 005 baseline of ~487 tokens
  had grown alongside the catalog. 1600 restores 005's intended
  sample-value resolution (country top-20, style top-50) while
  keeping a meaningful failsafe.

### What the budget guarantees

The column lists for the two wide tables (`release_fact`,
`release_unique_view` each carry ~35 columns) already consume
~400 tokens before any samples, so a tighter budget would fire
truncation on every cold start. The current 1600 ceiling is
still <2% of the cheap-model context window — the budget is a
discipline ceiling, not a cost ceiling.

If the catalog grows past the budget the producer truncates
samples in this order:

1. `country` top-20 → top-10
2. `style` top-50 → top-30
3. log a structured warning
   `schema_context_truncated_for_token_budget` with the new
   sizes

If even the truncated block exceeds the budget the producer
emits a higher-severity warning and proceeds with the
truncated set (graceful degradation; the LLM still gets *some*
sample values).

## Consumer rules

*Added 2026-05-04 as part of `006-bugfix-postmortem`. Codifies
Constitution VII.b — Prompt-authoring discipline. The original
T017–T020 wording in `tasks.md` ("swap the placeholder, keep
all other prompt structure intact") preserved redundant prose
in `router.md` that contradicted the rendered block when
`master_fact` became optional; this section makes the rule
explicit so future prompt edits cannot recreate the drift.*

Every prompt template that needs catalog schema information
MUST embed it **only** via the dynamically-rendered
`{schema_context_block}` placeholder produced by
`render_schema_block(...)`. The rendered block is the canonical,
single source of truth for:

- which tables exist and at what grain;
- which columns each table has;
- sample distinct values for low-cardinality columns;
- the domain glossary (decade-vs-year, style-vs-genre, ...);
- whether `master_fact` is present in the current snapshot.

Prompts MUST NOT contain static prose that *describes* any of
the above. Specifically, the following are forbidden in prompt
files:

- enumerations of available data ("the available data is
  RELEASE-LEVEL", "we have counts, styles, formats, ...") —
  these duplicate the table list inside the rendered block;
- references to specific table grains in prose (e.g.
  "release_fact has grain release × style") — these belong in
  the `table_grain` map inside `render_schema_block`;
- references to specific values that may exist or not exist
  ("Techno is a style on release_fact") — these are surfaced
  by sample values when present.

What prompts MAY (and should) contain:
- invariant *negative* lists — categories that are NEVER
  present in any catalog snapshot (prices, ratings, user
  counts, reviews). These do not depend on the snapshot and
  cannot drift.
- routing rules and output-shape contracts (JSON schemas,
  expected keys);
- task-specific instructions tied to the prompt's role
  (router classification taxonomy, code-generator template,
  etc.).

Reviewers MUST reject prompt edits that re-introduce static
schema prose, even if the prose happens to be correct on the
day it was written. The "happens to be correct" property does
not survive the next ETL change that adds or removes a table.

The "Join graph" section (added 2026-05-07 by
`009-schema-context-join-graph`) is also subject to the
consumer-rule constraint above: prompt templates MUST NOT
contain static prose that lists table relationships,
foreign-key pairs, or cross-grain traversal advice. All such
information flows only through the rendered block. Specifically
forbidden in prompt files:

- enumerations of foreign keys ("release_fact joins to bridges
  on release_id");
- statements about which join paths are correct or wrong
  ("don't join master_fact directly to bridges");
- worked SQL examples that demonstrate cross-grain joins.

These belong in the "Join graph" section of the rendered block,
where they can stay in sync with the published-DuckDB contracts.

## Backwards compatibility

All consumers that read only `tables` and `has_master_fact`
continue to work without changes. New fields are additive; old
prompts (if not yet edited) ignore the new placeholders.

## Caching

Process-local module-level cache. Cleared by
`reset_schema_cache()` (test helper) or process restart. The
cache MUST be populated at agent startup, NOT lazily on the
first request, so the first user query doesn't pay the
sample-build cost.
