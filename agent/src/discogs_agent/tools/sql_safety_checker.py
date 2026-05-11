"""Tool: sql_safety_checker.

Two-pass safety check per `contracts/sql-safety.md`:
  Pass 0 — DDL/DML keyword scan via sqlparse.
  Pass 1 — AST extraction of SQL strings + read_only=True assertion.
  Pass 2 — DuckDB EXPLAIN against an in-memory schema-stub catalog.
  Pass 3 — Forbidden-table re-scan (regex on the SQL string).
  Pass 4 — Forbidden cross-grain joins (added 014; regex + alias resolver).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from typing import Any

import duckdb
import sqlparse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from discogs_agent.duckdb_layer.allowlist import ALLOWED_TABLES, is_allowed
from discogs_agent.tools.base import traced_tool


class SafetyViolation(BaseModel):
    rule: str
    detail: str


class SafetyInput(BaseModel):
    generated_code: str
    schema_context: dict[str, Any]


class SafetyOutput(BaseModel):
    allowed: bool
    extracted_sql: str | None
    violations: list[SafetyViolation] = []
    explain_plan: str | None = None


_FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "COPY",
    "EXPORT",
    "IMPORT",
    "INSTALL",
    "LOAD",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
}

_FORBIDDEN_FUNCTION_PATTERNS = [
    re.compile(r"\bread_csv\b", re.IGNORECASE),
    re.compile(r"\bread_csv_auto\b", re.IGNORECASE),
    re.compile(r"\bread_parquet\b", re.IGNORECASE),
    re.compile(r"\bread_parquet_auto\b", re.IGNORECASE),
    re.compile(r"\bread_json\b", re.IGNORECASE),
    re.compile(r"\bread_blob\b", re.IGNORECASE),
    re.compile(r"\bread_text\b", re.IGNORECASE),
    re.compile(r"\bglob\s*\(", re.IGNORECASE),
    re.compile(r"\bparquet_metadata\b", re.IGNORECASE),
    re.compile(r"\bparquet_schema\b", re.IGNORECASE),
    re.compile(r"\bduckdb_extensions\b", re.IGNORECASE),
    re.compile(r"\bhttpfs", re.IGNORECASE),
    re.compile(r"\bs3_", re.IGNORECASE),
    re.compile(r"['\"]s3://", re.IGNORECASE),
    re.compile(r"['\"]https?://", re.IGNORECASE),
    re.compile(r"['\"]file://", re.IGNORECASE),
]


# ─── Pass 0: keyword scan ─────────────────────────────────────────────


def _scan_ddl_dml(sql: str) -> list[SafetyViolation]:
    violations: list[SafetyViolation] = []
    for stmt in sqlparse.parse(sql):
        first = stmt.token_first(skip_ws=True, skip_cm=True)  # type: ignore[no-untyped-call]
        if first is None:
            continue
        kw = first.normalized.upper()
        if kw in _FORBIDDEN_KEYWORDS:
            violations.append(SafetyViolation(rule="ddl_dml", detail=kw))
        elif kw not in {"SELECT", "WITH", "EXPLAIN"}:
            # Anything else first-token is suspicious.
            violations.append(SafetyViolation(rule="ddl_dml", detail=kw))
    return violations


def _scan_forbidden_functions(sql: str) -> list[SafetyViolation]:
    violations: list[SafetyViolation] = []
    for pattern in _FORBIDDEN_FUNCTION_PATTERNS:
        match = pattern.search(sql)
        if match:
            violations.append(SafetyViolation(rule="forbidden_function", detail=match.group(0)))
    return violations


# ─── Pass 1: AST extraction ───────────────────────────────────────────


_SQL_NAMES = {"sql", "query"}


class _SqlExtractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.captured: list[str] = []
        self.has_read_only_connect = False

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.lower() in _SQL_NAMES:
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    self.captured.append(value.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # con.execute("...") or duckdb.connect(...).execute("...").
        if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
            if node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    self.captured.append(node.args[0].value)
        # duckdb.connect(..., read_only=True)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "connect":
            for kw in node.keywords:
                if kw.arg == "read_only":
                    if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.has_read_only_connect = True
        self.generic_visit(node)


def _extract_sql(generated_code: str) -> tuple[str | None, bool, list[SafetyViolation]]:
    try:
        tree = ast.parse(generated_code)
    except SyntaxError as exc:
        return None, False, [SafetyViolation(rule="python_syntax", detail=str(exc))]

    extractor = _SqlExtractor()
    extractor.visit(tree)

    if not extractor.captured:
        return (
            None,
            extractor.has_read_only_connect,
            [
                SafetyViolation(
                    rule="no_sql_extracted", detail="no `sql=` or `.execute(...)` literal found"
                ),
            ],
        )
    # If multiple SQL strings, concat them and let pass-2 evaluate — in
    # V1 the canonical template emits exactly one.
    return extractor.captured[0], extractor.has_read_only_connect, []


# ─── Pass 2: EXPLAIN against in-memory schema stub ────────────────────


def _stub_explain_check(
    sql: str, schema_context: dict[str, Any]
) -> tuple[str | None, list[SafetyViolation]]:
    """Run EXPLAIN against an in-memory DuckDB whose catalog has the
    same allowlisted tables (empty stubs). Inspect the plan for
    references to non-allowlisted tables."""
    con = duckdb.connect(":memory:")
    try:
        tables = schema_context.get("tables", {})
        if not isinstance(tables, dict):
            return None, [SafetyViolation(rule="schema_context", detail="missing tables")]
        for tbl, cols in tables.items():
            col_defs = ", ".join(
                f'"{(c["name"] if isinstance(c, dict) else c.name)}" {(c["type"] if isinstance(c, dict) else c.type)}'
                for c in cols
            )
            try:
                con.execute(f'CREATE TABLE "{tbl}" ({col_defs})')
            except duckdb.Error:
                # Some types may not parse as DuckDB DDL types; fall back to VARCHAR.
                fallback = ", ".join(
                    f'"{(c["name"] if isinstance(c, dict) else c.name)}" VARCHAR' for c in cols
                )
                con.execute(f'CREATE TABLE "{tbl}" ({fallback})')

        # release_unique_view is a real view in the prod DuckDB — for
        # the explain check we register it as a table too.

        try:
            plan_rows = con.execute(f"EXPLAIN {sql}").fetchall()
        except duckdb.Error as exc:
            return None, [SafetyViolation(rule="sql_invalid", detail=str(exc))]

        plan_text = "\n".join(str(r[1]) if len(r) > 1 else str(r[0]) for r in plan_rows)
        violations: list[SafetyViolation] = []

        # Scan for forbidden function patterns in the plan text too —
        # belt-and-braces for read_csv / read_parquet that snuck through.
        for pat in _FORBIDDEN_FUNCTION_PATTERNS:
            m = pat.search(plan_text)
            if m:
                violations.append(SafetyViolation(rule="forbidden_function", detail=m.group(0)))

        return plan_text, violations
    finally:
        con.close()


# ─── Wired-up tool ───────────────────────────────────────────────────


def _build(
    session_provider: Callable[[], Session | None] | None = None,
) -> Callable[[SafetyInput], SafetyOutput]:
    @traced_tool("sql_safety_checker", session_provider=session_provider)
    def sql_safety_checker(payload: SafetyInput) -> SafetyOutput:
        # AST first — produces the SQL string + read_only flag.
        extracted, has_ro, ast_violations = _extract_sql(payload.generated_code)
        if ast_violations:
            return SafetyOutput(
                allowed=False,
                extracted_sql=extracted,
                violations=ast_violations,
            )
        if not has_ro:
            return SafetyOutput(
                allowed=False,
                extracted_sql=extracted,
                violations=[
                    SafetyViolation(
                        rule="read_only_required",
                        detail="duckdb.connect() must use read_only=True",
                    ),
                ],
            )
        if extracted is None:
            return SafetyOutput(
                allowed=False,
                extracted_sql=None,
                violations=[SafetyViolation(rule="no_sql_extracted", detail="empty")],
            )

        # Pass 0 — DDL/DML scan on the extracted SQL.
        ddl_violations = _scan_ddl_dml(extracted)
        if ddl_violations:
            return SafetyOutput(
                allowed=False,
                extracted_sql=extracted,
                violations=ddl_violations,
            )

        # Pre-explain: forbidden function pattern scan on the raw SQL.
        fn_violations = _scan_forbidden_functions(extracted)
        if fn_violations:
            return SafetyOutput(
                allowed=False,
                extracted_sql=extracted,
                violations=fn_violations,
            )

        # Pass 2 — explain.
        plan_text, explain_violations = _stub_explain_check(extracted, payload.schema_context)

        if explain_violations:
            return SafetyOutput(
                allowed=False,
                extracted_sql=extracted,
                violations=explain_violations,
                explain_plan=plan_text,
            )

        # Forbidden-table check via the schema_context, since EXPLAIN
        # would simply fail with "table not found" rather than route
        # through our explicit allowlist message. Re-scan the SQL for
        # any FROM/JOIN identifier that isn't in the allowlist.
        forbidden_table = _scan_forbidden_tables(extracted, payload.schema_context)
        if forbidden_table:
            return SafetyOutput(
                allowed=False,
                extracted_sql=extracted,
                violations=forbidden_table,
                explain_plan=plan_text,
            )

        # Forbidden cross-grain joins (added 014). Conditional on
        # has_master_fact — when master_fact is absent, the cross-grain
        # bug class is structurally unreachable. See
        # specs/014-cross-grain-join-postmortem/contracts/sandbox-exception-taxonomy.md.
        has_master_fact = bool(payload.schema_context.get("has_master_fact"))
        if has_master_fact:
            forbidden_join = _scan_forbidden_joins(extracted)
            if forbidden_join:
                return SafetyOutput(
                    allowed=False,
                    extracted_sql=extracted,
                    violations=forbidden_join,
                    explain_plan=plan_text,
                )

        return SafetyOutput(
            allowed=True,
            extracted_sql=extracted,
            violations=[],
            explain_plan=plan_text,
        )

    return sql_safety_checker


_TABLE_REF_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _scan_forbidden_tables(
    sql: str,
    schema_context: dict[str, Any],
) -> list[SafetyViolation]:
    """Catch references to tables not in the runtime allowlist (which
    excludes master_fact when the snapshot lacks it)."""
    runtime_tables = (
        set(schema_context.get("tables", {}).keys())
        if isinstance(schema_context.get("tables"), dict)
        else set()
    )
    violations: list[SafetyViolation] = []
    referenced = {m.group(1) for m in _TABLE_REF_PATTERN.finditer(sql)}
    for ref in referenced:
        # CTE names defined within the query itself are also matched
        # by the regex above; we exclude any name introduced by a
        # `WITH <name> AS (...)` clause.
        if _is_cte_alias(sql, ref):
            continue
        if ref in runtime_tables:
            continue
        if ref in ALLOWED_TABLES and ref not in runtime_tables:
            # In the global allowlist but not in this snapshot — e.g.
            # master_fact when has_master_fact is false.
            violations.append(
                SafetyViolation(
                    rule="forbidden_table",
                    detail=f"{ref} (not present in this snapshot)",
                )
            )
        elif not is_allowed(ref):
            violations.append(SafetyViolation(rule="forbidden_table", detail=ref))
    return violations


# `<ident> AS (` is an unambiguous CTE-definition shape. Other `AS`
# uses in SQL (column aliases, type casts, lateral subqueries) are
# never followed by an open paren on the right-hand side. Scanning
# the whole statement avoids the trap of trying to bound the WITH
# clause with a non-greedy regex — multi-CTE statements have an
# inner SELECT inside the *first* CTE body, which would terminate a
# `WITH … SELECT` non-greedy match prematurely and leave every CTE
# after the first looking like a forbidden-table reference.
_CTE_DEFINITION_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(",
    re.IGNORECASE,
)


def _is_cte_alias(sql: str, name: str) -> bool:
    """True iff `name` appears in the SQL as a CTE definition."""
    aliases = {m.group(1) for m in _CTE_DEFINITION_PATTERN.finditer(sql)}
    return name in aliases


# ──────────────────────────────────────────────────────────────────────
# Forbidden cross-grain joins (added 014-cross-grain-join-postmortem).
#
# Promotes the forbidden-joins list from descriptive prose in the
# rendered schema-context block (009's contribution) to runtime
# enforcement. Catches LLM hallucinations of cross-grain joins (e.g.,
# `master_fact.master_id = release_artist_bridge.release_id`) that
# pre-014 would silently produce a wrong answer because DuckDB happily
# executes the syntactically-valid (but semantically-meaningless) SQL.
#
# Canonical spec: specs/014-cross-grain-join-postmortem/contracts/
#   amendment-004-sql-safety.md §2.4 + §3.2.4.
# Mirrored in rendered prose: schema.py _render_join_graph "Forbidden
#   joins" sub-block (lines 251–260).
#
# Adding a pair is a contract amendment to 004/contracts/sql-safety.md.
# Each pair is (left_table, left_col, right_table, right_col). The
# scanner checks both orientations (predicate is symmetric).
# ──────────────────────────────────────────────────────────────────────

_FORBIDDEN_JOIN_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("master_fact", "master_id", "release_artist_bridge", "release_id"),
    ("master_fact", "master_id", "release_label_bridge", "release_id"),
    ("master_fact", "main_release_id", "release_artist_bridge", "release_id"),
    ("master_fact", "main_release_id", "release_label_bridge", "release_id"),
)

# `main_release_id` joins are sometimes legitimate (the operator wants
# only the primary release of each master). The rule still fires (hard
# reject — see research §R2), but the detail string includes a hint so
# the LLM can adjust on retry.
_MAIN_RELEASE_ID_HINT = (
    " (use the master_id traversal instead unless you specifically "
    "need the primary release of each master)"
)


def _strip_comments(sql: str) -> str:
    """Strip SQL comments via sqlparse before pattern scanning.

    Defends against false-positives where the SQL legitimately mentions
    a forbidden join pair inside a comment (e.g., LLM-generated
    documentation).
    """
    return sqlparse.format(sql, strip_comments=True)


# SQL keywords that may follow a table reference without introducing an
# alias. Used in the negative lookahead below to prevent the optional
# alias group from greedily consuming the next keyword (e.g., `JOIN` in
# `FROM master_fact JOIN release_artist_bridge`), which would mask the
# next JOIN's table from finditer.
_SQL_KEYWORDS_AFTER_TABLE: frozenset[str] = frozenset({
    "ON", "WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "JOIN",
    "LEFT", "RIGHT", "INNER", "FULL", "CROSS", "OUTER", "UNION",
    "INTERSECT", "EXCEPT", "WITH",
})

_KEYWORDS_LOOKAHEAD = r"(?:" + "|".join(sorted(_SQL_KEYWORDS_AFTER_TABLE)) + r")\b"

# Match `FROM <table> [AS] <alias>` and `JOIN <table> [AS] <alias>`.
# Both `FROM master_fact mf` and `FROM master_fact AS mf` are valid.
# Captures: (1) underlying table name, (2) alias (or empty).
#
# The negative lookahead `(?!_KEYWORDS_LOOKAHEAD)` prevents the optional
# alias group from consuming the next SQL keyword as a phantom alias.
# Without it, `FROM master_fact JOIN release_artist_bridge` would match
# (table=master_fact, alias=JOIN) and `re.finditer` would skip past the
# `JOIN`, never matching the next table.
_TABLE_ALIAS_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+(?:AS\s+)?(?!" + _KEYWORDS_LOOKAHEAD + r")([A-Za-z_][A-Za-z0-9_]*))?",
    re.IGNORECASE,
)


def _build_alias_map(sql: str) -> dict[str, str]:
    """Build a {alias_or_table: underlying_table} map from FROM/JOIN clauses.

    Bare-table references (no alias) self-map. Aliased references map to
    their underlying table. Used to resolve `mf.master_id` →
    `master_fact.master_id` before checking against
    `_FORBIDDEN_JOIN_PAIRS`.
    """
    alias_map: dict[str, str] = {}
    for match in _TABLE_ALIAS_PATTERN.finditer(sql):
        table = match.group(1)
        alias = match.group(2)
        # Self-map the table name (so `master_fact.master_id` resolves
        # to itself even when the query doesn't alias it).
        alias_map[table] = table
        if alias and alias.upper() not in _SQL_KEYWORDS_AFTER_TABLE:
            # Don't self-map a CTE alias to a real table (the CTE name
            # captured by _CTE_DEFINITION_PATTERN is what should be
            # treated as table-like, but its "underlying table" is the
            # CTE itself — we leave CTE refs unmapped so they don't
            # accidentally match forbidden-pair entries).
            if not _is_cte_alias(sql, table):
                alias_map[alias] = table
    return alias_map


# Match `<ref> = <ref>` where each ref is `<alias_or_table>.<column>`.
# This catches the predicate shape `mf.master_id = rab.release_id`
# anywhere in the SQL (typically inside an ON clause, but we don't
# bind to ON specifically — a WHERE clause join via implicit syntax
# would also be caught, which is desirable).
_PREDICATE_PATTERN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)"
    r"\s*=\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)",
)


def _scan_forbidden_joins(sql: str) -> list[SafetyViolation]:
    """Detect forbidden cross-grain join predicates in the extracted SQL.

    Three-stage algorithm per research §R1:
      1. Strip SQL comments.
      2. Build the alias map from FROM/JOIN clauses.
      3. Scan for `<ref>.<col> = <ref>.<col>` predicates; resolve aliases
         and check against `_FORBIDDEN_JOIN_PAIRS` in both orientations.

    Returns one SafetyViolation per matched predicate. Detail string uses
    unqualified table names in canonical form.
    """
    cleaned = _strip_comments(sql)
    alias_map = _build_alias_map(cleaned)

    violations: list[SafetyViolation] = []
    seen: set[tuple[str, str, str, str]] = set()  # dedupe identical hits

    for match in _PREDICATE_PATTERN.finditer(cleaned):
        ref_a, col_a, ref_b, col_b = match.group(1, 2, 3, 4)
        table_a = alias_map.get(ref_a)
        table_b = alias_map.get(ref_b)
        if table_a is None or table_b is None:
            # Either side refers to an unknown alias (e.g., a CTE-
            # indirected case — see research §R1 known gap).
            continue

        for pair in _FORBIDDEN_JOIN_PAIRS:
            pl_t, pl_c, pr_t, pr_c = pair
            # Check both orientations (predicate is symmetric).
            forward = (table_a, col_a, table_b, col_b) == pair
            reverse = (table_b, col_b, table_a, col_a) == pair
            if not (forward or reverse):
                continue

            key = pair if forward else (table_b, col_b, table_a, col_a)
            if key in seen:
                break
            seen.add(key)

            detail = f"{pl_t}.{pl_c} = {pr_t}.{pr_c}"
            if pl_c == "main_release_id":
                detail += _MAIN_RELEASE_ID_HINT
            violations.append(SafetyViolation(rule="forbidden_join", detail=detail))
            break  # don't double-emit for the same pair

    return violations


sql_safety_checker = _build()


def make_sql_safety_checker(
    session_provider: Callable[[], Session | None],
) -> Callable[[SafetyInput], SafetyOutput]:
    return _build(session_provider)
