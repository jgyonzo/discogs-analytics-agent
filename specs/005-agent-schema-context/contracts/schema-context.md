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

3) release_fact has grain release × style; counts of unique
   releases use COUNT(DISTINCT release_id) or
   release_unique_view.
```

## Token budget

`rendered_token_count` MUST be ≤ 1200. The producer computes it
using `tiktoken` (graceful fallback to `cl100k_base` if the
model alias isn't recognised). The 1200 budget reflects measured
reality on the April 2026 full-dump catalog: the column lists
for the two wide tables (`release_fact`, `release_unique_view`
each carry ~35 columns) already consume ~400 tokens before any
samples, so a tighter budget would fire truncation on every
cold start. 1200 tokens is still <8% of the cheap-model context
window. If the catalog grows past the budget the producer
truncates samples in this order:

1. `country` top-20 → top-10
2. `style` top-50 → top-30
3. log a structured warning
   `schema_context_truncated_for_token_budget` with the new
   sizes

If even the truncated block exceeds the budget the producer
emits a higher-severity warning and proceeds with the
truncated set (graceful degradation; the LLM still gets *some*
sample values).

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
