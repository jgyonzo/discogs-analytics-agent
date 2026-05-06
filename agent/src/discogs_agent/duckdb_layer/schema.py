"""Read the published DuckDB's allowlisted shape into an in-memory
`SchemaContext`. Module-level cache; built once at startup, reused by
every request. Refreshed only on process restart.

Phase 005 extension: the context now also carries a sampled-values
block (top-N distinct values for low-cardinality categorical
columns), a domain glossary, a pre-rendered prompt block, and a
token count enforced against a budget. The rendered block is the
single source of truth for the `{schema_context_block}` placeholder
used by every LLM-prompt-rendering function.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import duckdb

from discogs_agent.duckdb_layer.allowlist import (
    ALLOWED_TABLES,
    is_explicitly_forbidden,
)
from discogs_agent.observability import logging as obslog

logger = obslog.get_logger(__name__)


class SampleValue(TypedDict):
    value: Any
    count: int


class SchemaContext(TypedDict):
    tables: dict[str, list[dict[str, str]]]
    has_master_fact: bool
    duckdb_path: str
    captured_at: str
    warnings: list[str]
    sample_values: dict[str, dict[str, list[SampleValue]]]
    domain_glossary: list[str]
    published_run_id: str | None
    rendered_block: str
    rendered_token_count: int


_CORE_TABLES_REQUIRED = (
    "release_fact",
    "release_unique_view",
    "release_artist_bridge",
    "release_label_bridge",
)

# Sample-value plan: which columns to surface, on which table, with what cap.
# `None` for cap means "all distinct values" (used when cardinality is small
# and the values themselves are the whole point — e.g., primary_genre's 14
# buckets).
_SAMPLE_PLAN: tuple[tuple[str, str, int | None], ...] = (
    ("release_unique_view", "primary_genre", None),
    ("release_unique_view", "primary_format_group", None),
    ("release_unique_view", "decade", None),
    ("release_unique_view", "country", 20),
    ("release_fact", "style", 50),
)

# Budget set against the rendered output of the published catalog: 35+
# columns × 2 wide tables already eat ~400 tokens before any samples,
# so a 600-budget would fire truncation on every cold start. 1200 is
# the comfortable headroom; we still truncate before the prompt gets
# pathological.
_TOKEN_BUDGET = 1200
_TIKTOKEN_FALLBACK_ENCODING = "cl100k_base"

# Sample-truncation order when the rendered block exceeds the budget.
# Each entry is (table, column, new_cap). The runtime applies these in
# order until the block fits.
_TRUNCATION_STEPS: tuple[tuple[str, str, int], ...] = (
    ("release_unique_view", "country", 10),
    ("release_fact", "style", 30),
)

_DOMAIN_GLOSSARY: tuple[str, ...] = (
    "primary_genre is the coarse bucket (Rock, Electronic, Pop, Jazz, ...). "
    "style is the granular subgenre (Techno, House, Ambient, ...). "
    "Filter by 'style' on release_fact for subgenre questions; filter by "
    "'primary_genre' on release_unique_view only when the value literally "
    "appears in the primary_genre sample below.",
    "For 'evolution / over time / trend' questions WITHOUT explicit yearly "
    "granularity, group by `decade` not `year`. Override only when the "
    "user says 'year', 'yearly', or 'annual'.",
    "release_fact has grain release × style; counts of unique releases use "
    "COUNT(DISTINCT release_id) or query release_unique_view.",
)


_cache: SchemaContext | None = None


def _build_domain_glossary() -> list[str]:
    return list(_DOMAIN_GLOSSARY)


def _collect_sample_values(
    con: duckdb.DuckDBPyConnection,
    present_tables: set[str],
) -> dict[str, dict[str, list[SampleValue]]]:
    """Issue a small batch of bounded GROUP-BY queries to surface the
    most common values for the categorical columns the LLM cares about.
    """
    out: dict[str, dict[str, list[SampleValue]]] = {}
    for table, column, cap in _SAMPLE_PLAN:
        if table not in present_tables:
            continue
        limit_clause = f"LIMIT {cap}" if cap is not None else ""
        try:
            rows = con.execute(
                f"""
                SELECT {column} AS v, COUNT(*) AS c
                FROM {table}
                WHERE {column} IS NOT NULL
                GROUP BY 1
                ORDER BY c DESC
                {limit_clause}
                """
            ).fetchall()
        except duckdb.Error as exc:
            logger.warning(
                "sample_values_query_failed",
                table=table,
                column=column,
                error=str(exc),
            )
            continue
        out.setdefault(table, {})[column] = [{"value": r[0], "count": int(r[1])} for r in rows]
    return out


def _get_published_run_id(con: duckdb.DuckDBPyConnection) -> str | None:
    """Read the most recent run_id from release_unique_view if the column
    is present. Returns None if the column is absent or the table is empty."""
    try:
        row = con.execute("SELECT MAX(run_id) FROM release_unique_view").fetchone()
    except duckdb.Error:
        return None
    if not row or row[0] is None:
        return None
    return str(row[0])


def _format_sample_value(v: Any) -> str:
    if isinstance(v, str):
        return v
    return repr(v)


def render_schema_block(
    tables: dict[str, list[dict[str, str]]],
    sample_values: dict[str, dict[str, list[SampleValue]]],
    glossary: list[str],
    has_master_fact: bool,
) -> str:
    """Plain-text rendering for prompt injection. Pinned by
    `specs/005-agent-schema-context/contracts/schema-context.md`.
    """
    lines: list[str] = ["Available tables (allowlist):", ""]
    table_grain = {
        "release_fact": "grain: release × style",
        "release_unique_view": "grain: one row per release",
        "release_artist_bridge": "grain: release × main artist",
        "release_label_bridge": "grain: release × label",
        "master_fact": "grain: master release",
    }
    for table, cols in tables.items():
        grain = table_grain.get(table, "")
        suffix = f" ({grain})" if grain else ""
        lines.append(f"- {table}{suffix}:")
        col_names = ", ".join(c["name"] for c in cols)
        lines.append(f"  {col_names}")
        lines.append("")

    if not has_master_fact:
        lines.append("master_fact is NOT present in this catalog; do not reference it.")
        lines.append("")

    if sample_values:
        lines.append("Sample distinct values for low-cardinality columns:")
        lines.append("")
        for table, by_col in sample_values.items():
            for column, values in by_col.items():
                preview = ", ".join(_format_sample_value(s["value"]) for s in values)
                count_note = f"(top {len(values)})" if len(values) > 0 else "(none)"
                lines.append(f"- {table}.{column} {count_note}: {preview}.")
        lines.append("")

    if glossary:
        lines.append("Domain glossary:")
        lines.append("")
        for i, item in enumerate(glossary, 1):
            lines.append(f"{i}) {item}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _count_tokens(text: str, model: str | None = None) -> int:
    """Token count via tiktoken. Graceful fallback to cl100k_base when the
    requested model isn't recognised (newer aliases sometimes lag the
    library)."""
    try:
        import tiktoken
    except ImportError:
        return max(1, len(text) // 4)
    try:
        if model:
            enc = tiktoken.encoding_for_model(model)
        else:
            enc = tiktoken.get_encoding(_TIKTOKEN_FALLBACK_ENCODING)
    except (KeyError, ValueError):
        enc = tiktoken.get_encoding(_TIKTOKEN_FALLBACK_ENCODING)
    return len(enc.encode(text))


def _truncate_to_budget(
    tables: dict[str, list[dict[str, str]]],
    sample_values: dict[str, dict[str, list[SampleValue]]],
    glossary: list[str],
    has_master_fact: bool,
    model: str | None = None,
    budget: int = _TOKEN_BUDGET,
) -> tuple[dict[str, dict[str, list[SampleValue]]], str, int]:
    """Render the block; if over budget, drop tail samples per
    `_TRUNCATION_STEPS` and re-render. Returns the (possibly truncated)
    samples, the rendered block, and the final token count."""
    samples = {t: {c: list(vs) for c, vs in by_col.items()} for t, by_col in sample_values.items()}
    rendered = render_schema_block(tables, samples, glossary, has_master_fact)
    tokens = _count_tokens(rendered, model)
    if tokens <= budget:
        return samples, rendered, tokens

    for table, column, new_cap in _TRUNCATION_STEPS:
        if table in samples and column in samples[table]:
            old_cap = len(samples[table][column])
            if old_cap > new_cap:
                samples[table][column] = samples[table][column][:new_cap]
                logger.warning(
                    "schema_context_truncated_for_token_budget",
                    table=table,
                    column=column,
                    old_cap=old_cap,
                    new_cap=new_cap,
                    budget=budget,
                    tokens_before=tokens,
                )
                rendered = render_schema_block(tables, samples, glossary, has_master_fact)
                tokens = _count_tokens(rendered, model)
                if tokens <= budget:
                    return samples, rendered, tokens

    if tokens > budget:
        logger.warning(
            "schema_context_over_budget_after_truncation",
            tokens=tokens,
            budget=budget,
        )
    return samples, rendered, tokens


def read_schema_context(duckdb_path: str | Path) -> SchemaContext:
    """Open DuckDB read-only and snapshot the allowlisted catalog plus
    its sample values, glossary, and rendered prompt block.

    Raises FileNotFoundError if the file is absent.
    Raises RuntimeError if any of the four core tables is absent.
    `master_fact` is optional and reflected in `has_master_fact`.
    """
    path = Path(duckdb_path)
    if not path.exists():
        raise FileNotFoundError(f"DuckDB not found at {path}")

    # The published DuckDB is mounted read-only, so DuckDB cannot
    # create its default `<dbfile>.tmp/` spill dir adjacent to the file.
    # Point it at a writable tmpfs dir instead so big GROUP BYs in
    # _collect_sample_values don't fail with "Read-only file system".
    con = duckdb.connect(
        str(path),
        read_only=True,
        config={"temp_directory": "/tmp/duckdb"},
    )
    try:
        rows = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        present = {r[0] for r in rows}

        warnings: list[str] = []
        for name in present:
            if is_explicitly_forbidden(name):
                warnings.append(
                    f"Found non-allowlisted table {name!r} in published DuckDB; filtered out"
                )

        missing_core = [t for t in _CORE_TABLES_REQUIRED if t not in present]
        if missing_core:
            raise RuntimeError(
                f"Published DuckDB is missing required core tables: {missing_core}. "
                "Re-run the ETL on this snapshot."
            )

        tables: dict[str, list[dict[str, str]]] = {}
        for table in ALLOWED_TABLES:
            if table not in present:
                continue
            col_rows = con.execute(
                f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = '{table}'
                ORDER BY ordinal_position
                """
            ).fetchall()
            tables[table] = [{"name": c[0], "type": c[1]} for c in col_rows]

        has_master = "master_fact" in tables

        raw_samples = _collect_sample_values(con, set(tables.keys()))
        glossary = _build_domain_glossary()
        published_run_id = _get_published_run_id(con)

        samples, rendered_block, token_count = _truncate_to_budget(
            tables, raw_samples, glossary, has_master
        )

        return SchemaContext(
            tables=tables,
            has_master_fact=has_master,
            duckdb_path=str(path),
            captured_at=datetime.now(UTC).isoformat(),
            warnings=warnings,
            sample_values=samples,
            domain_glossary=glossary,
            published_run_id=published_run_id,
            rendered_block=rendered_block,
            rendered_token_count=token_count,
        )
    finally:
        con.close()


def get_schema_context(duckdb_path: str | Path) -> SchemaContext:
    """Cached accessor. Returns the same context across calls in one process."""
    global _cache
    if _cache is None:
        _cache = read_schema_context(duckdb_path)
    return _cache


def reset_schema_cache() -> None:
    """Test helper."""
    global _cache
    _cache = None
