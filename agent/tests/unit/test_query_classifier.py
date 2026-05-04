"""Tests for the query_classifier tool against the LLM stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from discogs_agent.duckdb_layer import schema as schema_module
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.dataset_schema_reader import (
    SchemaReaderInput,
    dataset_schema_reader,
)
from discogs_agent.tools.query_classifier import ClassifierInput, query_classifier


@pytest.fixture
def schema(seed_duckdb: Path, llm_stub: None) -> dict:
    schema_module.reset_schema_cache()
    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=str(seed_duckdb)))
    return out.model_dump()


def test_simple_query_routes_to_simple(schema: dict) -> None:
    with use_node("router"):
        out = query_classifier(
            ClassifierInput(user_query="Show releases by decade.", schema_context=schema)
        )
    assert out.complexity == "simple"
    assert out.selected_model is not None


def test_complex_query_routes_to_complex(schema: dict) -> None:
    with use_node("router"):
        out = query_classifier(
            ClassifierInput(
                user_query="Which labels have the most stylistic diversity?",
                schema_context=schema,
            )
        )
    assert out.complexity == "complex"
    assert out.selected_model is not None


def test_price_query_is_unsupported(schema: dict) -> None:
    with use_node("router"):
        out = query_classifier(
            ClassifierInput(
                user_query="What is the average price of Techno releases?",
                schema_context=schema,
            )
        )
    assert out.complexity == "unsupported"
    assert out.selected_model is None


def test_ambiguous_query_needs_clarification(schema: dict) -> None:
    with use_node("router"):
        out = query_classifier(
            ClassifierInput(
                user_query="Show me the best labels.",
                schema_context=schema,
            )
        )
    assert out.complexity == "clarification_needed"
    assert out.selected_model is None


def test_techno_query_routes_to_simple_not_unsupported(schema: dict) -> None:
    """005-agent-schema-context regression: 'Techno' is a valid `style`
    value surfaced in the enriched schema_context's sample block. The
    router MUST classify it as simple/complex, NOT unsupported."""
    assert "rendered_block" in schema
    assert "Techno" in schema["rendered_block"]
    with use_node("router"):
        out = query_classifier(
            ClassifierInput(
                user_query="Show the evolution of Techno releases over time",
                schema_context=schema,
            )
        )
    assert out.complexity in ("simple", "complex"), (
        f"Techno query routed to {out.complexity!r}; should be simple/complex "
        "since 'Techno' appears in the style sample of the schema context."
    )
    assert out.selected_model is not None
