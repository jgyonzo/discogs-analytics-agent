"""Unit tests for the enriched SchemaContext shape (feature 005).

Validates that the SchemaContext produced by `read_schema_context()`
includes the new fields, the rendered block contains the
expected sections, and the token-budget enforcement fires when the
budget is artificially small. Anchors SC-003, SC-004 (test
coverage).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from discogs_agent.duckdb_layer import schema as schema_module
from discogs_agent.duckdb_layer.schema import (
    read_schema_context,
    render_schema_block,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    schema_module.reset_schema_cache()


def test_schema_context_has_new_fields(seed_duckdb: Path) -> None:
    ctx = read_schema_context(str(seed_duckdb))
    for key in (
        "tables", "has_master_fact", "duckdb_path", "captured_at",
        "warnings", "sample_values", "domain_glossary",
        "published_run_id", "rendered_block", "rendered_token_count",
    ):
        assert key in ctx, f"missing key {key!r}"


def test_schema_context_sample_values_for_seed(seed_duckdb: Path) -> None:
    ctx = read_schema_context(str(seed_duckdb))
    samples = ctx["sample_values"]
    # release_unique_view samples — primary_genre is required.
    assert "release_unique_view" in samples
    assert "primary_genre" in samples["release_unique_view"]
    primary_genres = {
        s["value"] for s in samples["release_unique_view"]["primary_genre"]
    }
    assert "Electronic" in primary_genres
    # release_fact.style — must include the canonical styles seeded.
    assert "release_fact" in samples
    assert "style" in samples["release_fact"]
    styles = {s["value"] for s in samples["release_fact"]["style"]}
    assert "Techno" in styles
    assert "House" in styles
    assert "Funk" in styles


def test_schema_context_glossary_contains_style_vs_genre_rule(
    seed_duckdb: Path,
) -> None:
    ctx = read_schema_context(str(seed_duckdb))
    glossary = ctx["domain_glossary"]
    assert isinstance(glossary, list) and len(glossary) >= 2
    joined = "\n".join(glossary).lower()
    assert "primary_genre" in joined
    assert "style" in joined
    assert "decade" in joined and "year" in joined


def test_rendered_block_contains_required_sections(seed_duckdb: Path) -> None:
    ctx = read_schema_context(str(seed_duckdb))
    block = ctx["rendered_block"]
    assert "Available tables" in block
    assert "Sample distinct values" in block
    assert "Domain glossary" in block
    assert "release_fact" in block
    assert "Techno" in block  # at least one style sample renders


def test_rendered_block_under_budget(seed_duckdb: Path) -> None:
    ctx = read_schema_context(str(seed_duckdb))
    assert ctx["rendered_token_count"] <= 1200, (
        f"rendered_token_count={ctx['rendered_token_count']} exceeds the "
        "1200-token budget (SC-003)."
    )


def test_truncation_kicks_in_when_budget_is_tight(
    seed_duckdb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop the budget to a level the seed catalog can't fit and
    confirm truncation reduces sample sizes."""
    monkeypatch.setattr(schema_module, "_TOKEN_BUDGET", 100)
    ctx = read_schema_context(str(seed_duckdb))
    # The rendered block still exists even after truncation, even if
    # over-budget (graceful degradation).
    assert ctx["rendered_block"]
    # Truncated style sample should be smaller than the un-truncated
    # default cap of 50.
    samples = ctx["sample_values"]
    style_samples = samples.get("release_fact", {}).get("style", [])
    assert len(style_samples) <= 30, (
        f"truncation step should cap style at 30, got {len(style_samples)}"
    )


def test_render_schema_block_pure_function() -> None:
    """The renderer is a pure function — same inputs, same output."""
    tables = {"release_fact": [{"name": "release_id", "type": "BIGINT"}]}
    samples = {"release_fact": {"style": [{"value": "Techno", "count": 5}]}}
    glossary = ["A glossary line."]
    out_a = render_schema_block(tables, samples, glossary, has_master_fact=False)
    out_b = render_schema_block(tables, samples, glossary, has_master_fact=False)
    assert out_a == out_b
    assert "release_fact" in out_a
    assert "Techno" in out_a
    assert "A glossary line." in out_a
