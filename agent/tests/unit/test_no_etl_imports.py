"""Constitution Principle VI guard: no module under
`agent/src/discogs_agent/` may import from `discogs_etl.*`.

This test is load-bearing. Never skip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "discogs_agent"


def _python_files() -> list[Path]:
    return [p for p in AGENT_SRC.rglob("*.py") if p.is_file()]


def _imports_from_etl(tree: ast.AST) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "discogs_etl" or alias.name.startswith("discogs_etl."):
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "discogs_etl" or (
                node.module is not None and node.module.startswith("discogs_etl.")
            ):
                bad.append(node.module)
    return bad


def test_no_etl_imports() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover — surfaces config bugs
            pytest.fail(f"Failed to parse {path}: {exc}")
        bad = _imports_from_etl(tree)
        if bad:
            offenders[str(path)] = bad

    assert not offenders, (
        "Constitution Principle VI violation — agent imports ETL code:\n"
        + "\n".join(f"  {p}: {imps}" for p, imps in offenders.items())
    )
