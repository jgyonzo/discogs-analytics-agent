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
