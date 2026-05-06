"""FR-012 / SC-008 anchor: the code-generator prompt MUST contain the
count-rule paragraph verbatim.

If this test fails, code generation may produce SQL that miscounts
unique releases — a correctness bug for the agent's headline use case.
"""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "discogs_agent" / "prompts" / "code_generator.md"
)


def test_count_rule_in_code_generator_prompt() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    # The required phrase set:
    assert "release_fact" in text
    assert "COUNT(DISTINCT release_id)" in text
    assert "release_unique_view" in text
    assert "release × style" in text or "release x style" in text


def test_count_rule_present_in_repair_prompt() -> None:
    repair = PROMPT_PATH.parent / "repair_code.md"
    text = repair.read_text(encoding="utf-8")
    assert "COUNT(DISTINCT release_id)" in text
    assert "release_unique_view" in text
