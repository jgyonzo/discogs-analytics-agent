"""Node: load_schema.

Calls the dataset_schema_reader tool. Caches via the module-level
SchemaContext cache; subsequent invocations re-use it.
"""

from __future__ import annotations

from discogs_agent.config import settings
from discogs_agent.graph.state import AgentState
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.dataset_schema_reader import (
    SchemaReaderInput,
    dataset_schema_reader,
)


def load_schema_node(state: AgentState) -> AgentState:
    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=settings.ANALYTICS_DUCKDB_PATH))
    state["schema_context"] = out.model_dump()
    return state
