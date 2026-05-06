"""SC-007 anchor: the agent never mutates the published DuckDB.

We compute the SHA-256 of the seed DuckDB before and after running a
documented batch of queries (covering every routing path) and assert
byte equality.
"""

from __future__ import annotations

import hashlib


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_duckdb_byte_equal_after_query_batch(agent_env: dict) -> None:
    duckdb_path = agent_env["duckdb_path"]
    before = _sha256(duckdb_path)

    queries = [
        "Show releases by decade.",
        "Show the evolution of Techno releases over time",
        "What is the average price of Techno releases?",  # unsupported
        "Show me the best labels.",  # clarification
    ]
    for q in queries:
        resp = agent_env["post_query"](agent_env["QueryRequest"](message=q))
        assert resp.run_id  # smoke

    after = _sha256(duckdb_path)
    assert before == after, "DuckDB was mutated during query batch"
