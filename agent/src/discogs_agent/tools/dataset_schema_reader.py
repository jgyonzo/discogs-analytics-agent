"""Tool: dataset_schema_reader.

Wraps `duckdb_layer.schema.read_schema_context` so it can be invoked
through the @traced_tool persistence shim.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from discogs_agent.duckdb_layer.schema import SchemaContext, get_schema_context
from discogs_agent.tools.base import traced_tool


class TableColumn(BaseModel):
    name: str
    type: str


class SchemaReaderInput(BaseModel):
    duckdb_path: str


class SchemaReaderOutput(BaseModel):
    tables: dict[str, list[TableColumn]]
    has_master_fact: bool
    duckdb_path: str
    captured_at: str
    warnings: list[str] = []
    # 005-agent-schema-context: pass the enriched fields through so
    # the prompt-rendering nodes can use the pre-rendered block.
    sample_values: dict[str, dict[str, list[dict[str, Any]]]] = Field(default_factory=dict)
    domain_glossary: list[str] = Field(default_factory=list)
    published_run_id: str | None = None
    rendered_block: str = ""
    rendered_token_count: int = 0


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[SchemaReaderInput], SchemaReaderOutput]:
    @traced_tool("dataset_schema_reader", session_provider=session_provider)
    def dataset_schema_reader(payload: SchemaReaderInput) -> SchemaReaderOutput:
        ctx: SchemaContext = get_schema_context(payload.duckdb_path)
        return SchemaReaderOutput(
            tables={name: [TableColumn(**c) for c in cols] for name, cols in ctx["tables"].items()},
            has_master_fact=ctx["has_master_fact"],
            duckdb_path=ctx["duckdb_path"],
            captured_at=ctx["captured_at"],
            warnings=list(ctx.get("warnings", [])),
            sample_values={
                table: {col: [dict(sv) for sv in svs] for col, svs in cols.items()}
                for table, cols in ctx.get("sample_values", {}).items()
            },
            domain_glossary=list(ctx.get("domain_glossary", [])),
            published_run_id=ctx.get("published_run_id"),
            rendered_block=ctx.get("rendered_block", ""),
            rendered_token_count=int(ctx.get("rendered_token_count", 0)),
        )

    return dataset_schema_reader


# Module-level instance with no persistence binding (used by tests
# that don't supply a session). The graph wires its own instance with
# the request-scoped session.
dataset_schema_reader = _build()


def make_dataset_schema_reader(
    session_provider: Callable[[], Session | None],
) -> Callable[[SchemaReaderInput], SchemaReaderOutput]:
    """Factory for the request-scoped variant."""
    return _build(session_provider)
