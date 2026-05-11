"""Comprehensive tests for the sql_safety_checker tool.

Covers every row of `contracts/sql-safety.md §6`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from discogs_agent.duckdb_layer import schema as schema_module
from discogs_agent.observability.tracing import use_node
from discogs_agent.tools.dataset_schema_reader import (
    SchemaReaderInput,
    dataset_schema_reader,
)
from discogs_agent.tools.sql_safety_checker import SafetyInput, sql_safety_checker


@pytest.fixture
def schema(seed_duckdb: Path) -> dict:
    schema_module.reset_schema_cache()
    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=str(seed_duckdb)))
    return out.model_dump()


@pytest.fixture
def schema_no_master(seed_duckdb_no_master: Path) -> dict:
    schema_module.reset_schema_cache()
    with use_node("load_schema"):
        out = dataset_schema_reader(SchemaReaderInput(duckdb_path=str(seed_duckdb_no_master)))
    return out.model_dump()


def _wrap(sql: str, *, read_only: bool = True) -> str:
    """Wrap a raw SQL string in a minimal generated-code template."""
    ro = "True" if read_only else "False"
    return f'''import duckdb
import os
con = duckdb.connect(os.environ["ANALYTICS_DUCKDB_PATH"], read_only={ro})
sql = """{sql}"""
df = con.execute(sql).df()
'''


def _run(generated_code: str, schema: dict):
    with use_node("sql_safety_checker"):
        return sql_safety_checker(SafetyInput(generated_code=generated_code, schema_context=schema))


# ─── Pass 0 ── DDL/DML scan ──


def test_safety_blocks_drop(schema: dict) -> None:
    out = _run(_wrap("DROP TABLE release_fact"), schema)
    assert out.allowed is False
    assert any(v.rule == "ddl_dml" for v in out.violations)


def test_safety_blocks_insert(schema: dict) -> None:
    out = _run(
        _wrap(
            "INSERT INTO release_fact VALUES (1, 1990, 1995, 'US', TRUE, FALSE, 'Techno', 1, 'Electronic', NULL)"
        ),
        schema,
    )
    assert out.allowed is False
    assert any(v.rule == "ddl_dml" for v in out.violations)


# ─── Pass 0.5 ── forbidden function patterns ──


def test_safety_blocks_read_parquet(schema: dict) -> None:
    out = _run(_wrap("SELECT * FROM read_parquet('x.parquet')"), schema)
    assert out.allowed is False
    assert any(v.rule == "forbidden_function" for v in out.violations)


def test_safety_blocks_url_literal(schema: dict) -> None:
    out = _run(_wrap("SELECT 's3://bucket/file' AS x"), schema)
    assert out.allowed is False
    assert any(v.rule == "forbidden_function" for v in out.violations)


# ─── Pass 1 ── AST + read_only ──


def test_safety_requires_read_only(schema: dict) -> None:
    out = _run(_wrap("SELECT 1", read_only=False), schema)
    assert out.allowed is False
    assert any(v.rule == "read_only_required" for v in out.violations)


# ─── Pass 2 ── allowlist via EXPLAIN ──


def test_safety_blocks_stg_table(schema: dict) -> None:
    out = _run(_wrap("SELECT release_id FROM stg_releases"), schema)
    assert out.allowed is False
    # Either the EXPLAIN fails (sql_invalid since the stub lacks it) or
    # the forbidden_table scan catches it. Both are acceptable.
    assert any(v.rule in ("forbidden_table", "sql_invalid") for v in out.violations)


def test_safety_blocks_clean_table(schema: dict) -> None:
    out = _run(_wrap("SELECT release_id FROM clean_releases"), schema)
    assert out.allowed is False
    assert any(v.rule in ("forbidden_table", "sql_invalid") for v in out.violations)


def test_safety_blocks_format_summary(schema: dict) -> None:
    out = _run(_wrap("SELECT release_id FROM release_format_summary"), schema)
    assert out.allowed is False
    assert any(v.rule in ("forbidden_table", "sql_invalid") for v in out.violations)


def test_safety_blocks_master_fact_when_absent(schema_no_master: dict) -> None:
    out = _run(_wrap("SELECT * FROM master_fact"), schema_no_master)
    assert out.allowed is False
    assert any(v.rule in ("forbidden_table", "sql_invalid") for v in out.violations)


# ─── Happy path ──


def test_safety_passes_techno_query(schema: dict) -> None:
    sql = "SELECT year, COUNT(DISTINCT release_id) AS releases FROM release_fact WHERE style = 'Techno' GROUP BY year ORDER BY year"
    out = _run(_wrap(sql), schema)
    assert out.allowed is True, f"violations: {out.violations}"
    assert out.extracted_sql == sql
    assert out.explain_plan is not None and len(out.explain_plan) > 0


def test_safety_passes_label_diversity_query(schema: dict) -> None:
    sql = """
SELECT l.label_name,
       COUNT(DISTINCT f.style)      AS distinct_styles,
       COUNT(DISTINCT f.release_id) AS releases
FROM release_label_bridge l
JOIN release_fact f ON l.release_id = f.release_id
GROUP BY l.label_name
ORDER BY distinct_styles DESC
""".strip()
    out = _run(_wrap(sql), schema)
    assert out.allowed is True, f"violations: {out.violations}"


def test_safety_explain_plan_recorded(schema: dict) -> None:
    sql = "SELECT decade, COUNT(*) AS releases FROM release_unique_view GROUP BY decade"
    out = _run(_wrap(sql), schema)
    assert out.allowed is True
    assert out.explain_plan is not None
    assert len(out.explain_plan) > 0


# ─── Pass 4 ── Forbidden cross-grain joins (added 014) ──


def test_safety_blocks_forbidden_cross_grain_join_with_aliases(schema: dict) -> None:
    """The exact SQL from run 2557c2ce-... (the 014 trigger incident).

    LLM hallucinated `mf.master_id = rab.release_id` — literally the
    first entry in 009's forbidden-joins anti-pattern list. Both columns
    are BIGINT so DuckDB executed the join; the result was a meaningless
    top-5 driven by coincidental ID overlaps. Post-014 the safety
    checker MUST reject with rule="forbidden_join".
    """
    sql = """
WITH artist_master_count AS (
    SELECT
        rab.artist_name,
        COUNT(DISTINCT mf.master_id) AS work_version_count
    FROM master_fact mf
    JOIN release_artist_bridge rab ON mf.master_id = rab.release_id
    WHERE rab.artist_name NOT IN ('Various', 'Unknown Artist')
    GROUP BY rab.artist_name
)
SELECT artist_name, work_version_count
FROM artist_master_count
ORDER BY work_version_count DESC LIMIT 5
""".strip()
    out = _run(_wrap(sql), schema)
    assert out.allowed is False
    forbidden_join_violations = [v for v in out.violations if v.rule == "forbidden_join"]
    assert len(forbidden_join_violations) == 1, (
        f"expected exactly one forbidden_join violation, got: {out.violations}"
    )
    assert (
        forbidden_join_violations[0].detail
        == "master_fact.master_id = release_artist_bridge.release_id"
    )


def test_safety_blocks_forbidden_join_label_bridge_fully_qualified(schema: dict) -> None:
    """Label-bridge variant, fully qualified (no aliases). Same rule."""
    sql = """
SELECT release_label_bridge.label_name, COUNT(DISTINCT master_fact.master_id) AS works
FROM master_fact
JOIN release_label_bridge ON master_fact.master_id = release_label_bridge.release_id
GROUP BY release_label_bridge.label_name
""".strip()
    out = _run(_wrap(sql), schema)
    assert out.allowed is False
    assert any(
        v.rule == "forbidden_join"
        and v.detail == "master_fact.master_id = release_label_bridge.release_id"
        for v in out.violations
    )


def test_safety_blocks_main_release_id_with_legitimate_hint(schema: dict) -> None:
    """main_release_id variant: still hard-rejected per research §R2,
    but the detail string includes the legitimate-sometimes hint so the
    LLM can adjust on retry."""
    sql = """
SELECT rab.artist_name, COUNT(*) AS primary_releases
FROM master_fact mf
JOIN release_artist_bridge rab ON mf.main_release_id = rab.release_id
GROUP BY rab.artist_name
""".strip()
    out = _run(_wrap(sql), schema)
    assert out.allowed is False
    forbidden = [v for v in out.violations if v.rule == "forbidden_join"]
    assert len(forbidden) == 1
    assert "master_fact.main_release_id = release_artist_bridge.release_id" in forbidden[0].detail
    assert "primary release" in forbidden[0].detail  # the hint


def test_safety_passes_legitimate_release_fact_to_bridge_join(schema: dict) -> None:
    """Regression guard: the CORRECT release-grain join
    (release_fact.release_id = release_artist_bridge.release_id) MUST
    NOT trigger forbidden_join. This is the very pattern US1's hint
    update now recommends as the master → artist traversal path."""
    sql = """
SELECT rab.artist_name, COUNT(DISTINCT rf.master_id) AS works
FROM release_fact rf
JOIN release_artist_bridge rab ON rf.release_id = rab.release_id
WHERE rf.master_id IS NOT NULL
GROUP BY rab.artist_name
ORDER BY works DESC LIMIT 5
""".strip()
    out = _run(_wrap(sql), schema)
    assert out.allowed is True, f"violations: {out.violations}"
    assert not any(v.rule == "forbidden_join" for v in out.violations)


@pytest.mark.skip(
    reason="Known regex-scanner gap; CTE-indirection cases are not caught. "
    "Tracked in specs/014-cross-grain-join-postmortem/research.md §R1. "
    "Mitigation is the prompt-side hint update (US1)."
)
def test_safety_cte_indirected_forbidden_join_is_known_gap(schema: dict) -> None:
    """Documents the CTE-indirection gap: when the forbidden join hides
    inside a CTE, the regex-based alias resolver cannot trace the CTE
    column back to its source table. Future AST-based upgrade would
    close this gap; deferred per research §R1.
    """
    sql = """
WITH masters AS (
    SELECT master_id FROM master_fact
)
SELECT m.master_id, rab.artist_name
FROM masters m
JOIN release_artist_bridge rab ON m.master_id = rab.release_id
""".strip()
    out = _run(_wrap(sql), schema)
    # The rule does NOT fire (the gap). When this test is unskipped by
    # a future AST upgrade, assert: rule="forbidden_join" present.
    assert not any(v.rule == "forbidden_join" for v in out.violations)


def test_safety_forbidden_join_rule_conditional_on_master_fact(
    schema_no_master: dict,
) -> None:
    """When has_master_fact=False, the forbidden_join rule is skipped.

    In practice the forbidden-table check (Pass 3) fires first for
    SQL referencing master_fact when master_fact isn't in the runtime
    snapshot — but the conditional MUST be explicit. We use a SQL
    shape that doesn't reference master_fact at all to isolate the
    conditional: this should pass cleanly.
    """
    sql = """
SELECT rab.artist_name, COUNT(DISTINCT rf.release_id) AS releases
FROM release_fact rf
JOIN release_artist_bridge rab ON rf.release_id = rab.release_id
GROUP BY rab.artist_name
""".strip()
    out = _run(_wrap(sql), schema_no_master)
    # The legitimate join MUST pass even in the no-master-fact snapshot.
    assert out.allowed is True, f"violations: {out.violations}"
    assert not any(v.rule == "forbidden_join" for v in out.violations)


def test_safety_passes_multi_cte_comparison(schema: dict) -> None:
    """Regression: multi-CTE WITH clauses must not have their later
    CTE aliases misclassified as forbidden tables. The bound-the-
    WITH-block regex used to stop at the first inner SELECT, which
    is inside the *first* CTE body, leaving every later CTE alias
    looking like an unallowlisted table reference.
    """
    sql = """
WITH techno_releases AS (
    SELECT decade, COUNT(DISTINCT release_id) AS release_count
    FROM release_fact
    WHERE style = 'Techno' AND decade >= 1980
    GROUP BY decade
),
house_releases AS (
    SELECT decade, COUNT(DISTINCT release_id) AS release_count
    FROM release_fact
    WHERE style = 'House' AND decade >= 1980
    GROUP BY decade
)
SELECT
    COALESCE(t.decade, h.decade) AS decade,
    t.release_count AS techno_releases,
    h.release_count AS house_releases
FROM techno_releases t
FULL OUTER JOIN house_releases h ON t.decade = h.decade
ORDER BY decade
""".strip()
    out = _run(_wrap(sql), schema)
    assert out.allowed is True, f"violations: {out.violations}"
