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
        "tables",
        "has_master_fact",
        "duckdb_path",
        "captured_at",
        "warnings",
        "sample_values",
        "domain_glossary",
        "published_run_id",
        "rendered_block",
        "rendered_token_count",
    ):
        assert key in ctx, f"missing key {key!r}"


def test_schema_context_sample_values_for_seed(seed_duckdb: Path) -> None:
    ctx = read_schema_context(str(seed_duckdb))
    samples = ctx["sample_values"]
    # release_unique_view samples — primary_genre is required.
    assert "release_unique_view" in samples
    assert "primary_genre" in samples["release_unique_view"]
    primary_genres = {s["value"] for s in samples["release_unique_view"]["primary_genre"]}
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
    assert ctx["rendered_token_count"] <= 1600, (
        f"rendered_token_count={ctx['rendered_token_count']} exceeds the "
        "1600-token budget (post-011 recalibration)."
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


# ─── 009-schema-context-join-graph ─────────────────────────────────────────
# Regression tests for the "Join graph" section. Pinned by
# specs/009-schema-context-join-graph/contracts/amendment-005-schema-context.md.

_JOIN_GRAPH_TEST_TABLES = {
    "release_fact": [
        {"name": "release_id", "type": "BIGINT"},
        {"name": "master_id", "type": "BIGINT"},
        {"name": "style", "type": "VARCHAR"},
    ],
    "release_unique_view": [
        {"name": "release_id", "type": "BIGINT"},
        {"name": "master_id", "type": "BIGINT"},
    ],
    "release_artist_bridge": [
        {"name": "release_id", "type": "BIGINT"},
        {"name": "artist_name", "type": "VARCHAR"},
    ],
    "release_label_bridge": [
        {"name": "release_id", "type": "BIGINT"},
    ],
    "master_fact": [
        {"name": "master_id", "type": "BIGINT"},
        {"name": "decade", "type": "INTEGER"},
    ],
}


def test_join_graph_section_present_when_master_fact_true() -> None:
    """When the catalog has master_fact, the join-graph section
    delivers the master-side edges, the namespaces hint, and the
    explicit forbidden-join lines."""
    out = render_schema_block(
        _JOIN_GRAPH_TEST_TABLES,
        sample_values={},
        glossary=[],
        has_master_fact=True,
    )

    # Section header.
    assert "Join graph" in out

    # Edge list — at least the master-side edges are present.
    assert "release_unique_view.master_id  ↔  master_fact.master_id" in out
    assert "release_fact.master_id  ↔  master_fact.master_id" in out
    # Release-side edges are also present.
    assert "release_unique_view.release_id  ↔  release_artist_bridge.release_id" in out
    assert "release_unique_view.release_id  ↔  release_label_bridge.release_id" in out

    # Cross-grain traversal hint — the load-bearing line.
    assert (
        "different identifier namespaces" in out.lower() or "DIFFERENT identifier namespaces" in out
    )

    # Worked-example traversal — post-014 uses release_fact (not
    # release_unique_view) to resolve the contradiction with glossary
    # entry #3. See 014-cross-grain-join-postmortem.
    assert "master_fact -> release_fact (on master_id)" in out
    assert "-> release_artist_bridge (on release_id)" in out

    # Positive prohibition — post-014. The cross-grain hint MUST
    # explicitly state that release_unique_view is not a usable
    # traversal surface, so the LLM can't reach for it by default.
    assert "release_unique_view is NOT a usable traversal surface" in out

    # Forbidden joins — the canonical bug pattern.
    assert "master_fact.master_id  =  release_artist_bridge.release_id" in out
    assert "master_fact.master_id  =  release_label_bridge.release_id" in out


def test_join_graph_section_omits_master_when_master_fact_false() -> None:
    """When the catalog lacks master_fact, the join-graph section
    still renders (release-side edges present) but contains zero
    references to master_fact, master_id, or any master-side
    forbidden-join line."""
    tables_no_mf = {k: v for k, v in _JOIN_GRAPH_TEST_TABLES.items() if k != "master_fact"}
    out = render_schema_block(
        tables_no_mf,
        sample_values={},
        glossary=[],
        has_master_fact=False,
    )

    # Section still rendered.
    assert "Join graph" in out

    # Release-side edges present.
    assert "release_unique_view.release_id  ↔  release_artist_bridge.release_id" in out

    # No master-side content — neither the master_fact word nor the
    # master_id-side traversal hint nor the master forbidden-join lines.
    # Allow `master_id` to appear in the table-listing (release_fact has
    # a master_id column), so we scan the join-graph subsection only.
    join_graph_start = out.index("Join graph")
    join_graph_end = out.index("Domain glossary") if "Domain glossary" in out else len(out)
    join_graph_section = out[join_graph_start:join_graph_end]
    assert "master_fact" not in join_graph_section
    assert "DIFFERENT identifier namespaces" not in join_graph_section
    assert "Forbidden joins" not in join_graph_section


def test_join_graph_glossary_entry_about_bridge_grain() -> None:
    """The fourth glossary entry (added by 009) warns that bridges
    are not unique on release_id and that COUNT(*) double-counts."""
    out = render_schema_block(
        _JOIN_GRAPH_TEST_TABLES,
        sample_values={},
        glossary=list(schema_module._DOMAIN_GLOSSARY),
        has_master_fact=True,
    )
    # The glossary entry about bridge grain.
    assert "release_artist_bridge" in out and "release_label_bridge" in out
    assert "NOT unique on release_id" in out
    assert "COUNT(DISTINCT release_id)" in out
    assert "double-counts" in out


def test_join_graph_section_position_relative_to_other_sections() -> None:
    """Per contract: Join graph appears AFTER tables + samples and
    BEFORE the domain glossary."""
    out = render_schema_block(
        _JOIN_GRAPH_TEST_TABLES,
        sample_values={
            "release_fact": {
                "style": [{"value": "Techno", "count": 100}],
            }
        },
        glossary=["A glossary line."],
        has_master_fact=True,
    )
    tables_idx = out.index("Available tables")
    samples_idx = out.index("Sample distinct values")
    join_idx = out.index("Join graph")
    glossary_idx = out.index("Domain glossary")
    assert tables_idx < samples_idx < join_idx < glossary_idx
