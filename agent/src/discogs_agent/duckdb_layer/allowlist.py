"""The published-DuckDB allowlist.

This is the *positive* gate the agent enforces against the LLM-generated
SQL: any table or view referenced in generated SQL must appear in this
list (and, additionally, in the runtime SchemaContext.tables — so
master_fact is dropped when the snapshot lacks it).
"""

from __future__ import annotations

# Tables the agent is allowed to query.
ALLOWED_TABLES: tuple[str, ...] = (
    "release_fact",
    "release_unique_view",
    "release_artist_bridge",
    "release_label_bridge",
    "master_fact",
)

# Tables that should never be queried even if accidentally present in the
# published DuckDB. Used by the schema reader to filter and warn.
EXPLICITLY_FORBIDDEN_PREFIXES: tuple[str, ...] = ("stg_", "clean_")

EXPLICITLY_FORBIDDEN_TABLES: tuple[str, ...] = ("release_format_summary",)


def is_allowed(table_name: str) -> bool:
    """True iff the given table is in the allowlist."""
    return table_name in ALLOWED_TABLES


def is_explicitly_forbidden(table_name: str) -> bool:
    """True iff the given name should never appear in the agent's catalog."""
    if table_name in EXPLICITLY_FORBIDDEN_TABLES:
        return True
    return any(table_name.startswith(p) for p in EXPLICITLY_FORBIDDEN_PREFIXES)
