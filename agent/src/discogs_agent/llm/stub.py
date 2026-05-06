"""Deterministic in-process LLM stub.

Used by all unit, graph-path, and integration tests so no real API call
is needed. Routes responses by node name + a stable hash over the
user-query field of the prompt. Test-time configuration of canned
responses is via `set_responses(...)`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# (node_name, query_hash) -> raw response string. Tests populate this.
_responses: dict[tuple[str, str], str] = {}

# Default canned responses keyed by node + a low-cardinality query
# fingerprint, used when tests don't override.
_default_responses: dict[tuple[str, str], str] = {}


@dataclass
class _StubResponse:
    content: str
    usage: dict[str, int]


def _hash_query(query: str) -> str:
    """Stable 12-char hash of the user-query text."""
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:12]


def set_responses(items: dict[tuple[str, str], str]) -> None:
    """Replace stub responses for the duration of a test."""
    _responses.clear()
    _responses.update(items)


def reset() -> None:
    _responses.clear()


def register_default(node_name: str, query_pattern: str, response: str) -> None:
    """Register a default response keyed by (node, query_pattern_hash)."""
    _default_responses[(node_name, _hash_query(query_pattern))] = response


def _extract_user_query(messages: list[dict[str, str]]) -> str:
    """Find the user query in a messages list. Heuristic: last user
    message; if absent, last message of any role."""
    user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
    if user_msgs:
        return user_msgs[-1]
    if messages:
        return messages[-1].get("content", "")
    return ""


def _approx_tokens(text: str) -> int:
    """Cheap whitespace-token count; the stub doesn't need exact tiktoken
    accuracy for trace-shape testing."""
    return max(1, len(text) // 4)


class StubChatModel:
    """Stub conforming to the `ChatLike` protocol."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def invoke(self, messages: list[dict[str, str]]) -> _StubResponse:
        from discogs_agent.observability.tracing import node_context

        node = node_context.get()
        user_query = _extract_user_query(messages)
        qhash = _hash_query(user_query)

        # Tests override > query-pattern defaults > hard fallback.
        content = _responses.get((node, qhash))
        if content is None:
            content = _default_responses.get((node, qhash))
        if content is None:
            content = _fallback_for_node(node, user_query)

        prompt_text = "\n".join(m.get("content", "") for m in messages)
        return _StubResponse(
            content=content,
            usage={
                "prompt_tokens": _approx_tokens(prompt_text),
                "completion_tokens": _approx_tokens(content),
            },
        )


# ─── Fallback: if no test override and no default match, produce a
# minimal "this is the stub" response so tests fail loudly with a
# clear message rather than mysteriously. ─────────────────────────────


_PRICE_PATTERN = re.compile(r"\bprice\b", re.IGNORECASE)
_BEST_LABEL_PATTERN = re.compile(r"\bbest\s+labels?\b", re.IGNORECASE)
_YEARLY_PATTERN = re.compile(r"\b(year|yearly|annual)\b", re.IGNORECASE)

# Known style values. Mirrors the values the agent's enriched
# schema-context surfaces to the LLM in production. Keep the list
# tight — these are the styles the test suites exercise.
_KNOWN_STYLES: tuple[str, ...] = (
    "Techno",
    "House",
    "Ambient",
    "Drum n Bass",
    "Trance",
    "Dub",
    "Garage",
    "Disco",
    "Acid Jazz",
    "Funk",
)


def _detect_style(query: str) -> str | None:
    """Find the first known style mentioned in the user query, with
    a word-boundary match so 'House' doesn't accidentally fire on
    'household'."""
    q_lower = query.lower()
    for style in _KNOWN_STYLES:
        pattern = rf"\b{re.escape(style.lower())}\b"
        if re.search(pattern, q_lower):
            return style
    return None


def _fallback_for_node(node: str, user_query: str) -> str:
    """Sane defaults for the headline test queries."""
    q = user_query.lower()
    style = _detect_style(user_query)
    if node == "router":
        if _PRICE_PATTERN.search(q):
            return _ROUTER_UNSUPPORTED
        if _BEST_LABEL_PATTERN.search(q):
            return _ROUTER_CLARIFICATION
        if "diversity" in q or "outlier" in q or "stylistic" in q:
            return _ROUTER_COMPLEX
        return _ROUTER_SIMPLE
    if node == "query_understanding":
        if style:
            return _plan_for_style(style, user_query)
        return _PLAN_BY_DECADE
    if node == "code_generator":
        if style:
            return _code_for_style(style, user_query)
        return _CODE_BY_DECADE
    if node == "response_synthesizer":
        return "Generated a chart for your query."
    return f'{{"_stub_unhandled_node": "{node}"}}'


def _plan_for_style(style: str, user_query: str) -> str:
    grain = "year" if _YEARLY_PATTERN.search(user_query) else "decade"
    return (
        "{\n"
        '  "analysis_intent": "trend",\n'
        '  "tables": ["release_fact"],\n'
        f'  "dimensions": ["{grain}"],\n'
        '  "metrics": [{"name": "releases", "aggregation": "count_distinct", "column": "release_id"}],\n'
        f'  "filters": [{{"column": "style", "operator": "=", "value": "{style}"}}],\n'
        '  "chart_type": "line",\n'
        '  "notes": "Style filter on release_fact + COUNT DISTINCT release_id."\n'
        "}"
    )


def _code_for_style(style: str, user_query: str) -> str:
    grain = "year" if _YEARLY_PATTERN.search(user_query) else "decade"
    title = f"{style} releases over time"
    return (
        "import duckdb\n"
        "import pandas as pd\n"
        "import plotly.express as px\n"
        "from pathlib import Path\n"
        "import os\n"
        "\n"
        'DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]\n'
        'ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])\n'
        "ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)\n"
        "\n"
        'con = duckdb.connect(DB_PATH, read_only=True, config={"temp_directory": "/tmp/duckdb"})\n'
        "\n"
        'sql = """\n'
        f"SELECT {grain}, COUNT(DISTINCT release_id) AS releases\n"
        "FROM release_fact\n"
        f"WHERE style = '{style}' AND {grain} IS NOT NULL\n"
        f"GROUP BY {grain}\n"
        f"ORDER BY {grain}\n"
        '"""\n'
        "\n"
        "df = con.execute(sql).df()\n"
        "\n"
        f'fig = px.line(df, x="{grain}", y="releases", title="{title}")\n'
        'chart_path = ARTIFACT_DIR / "chart.html"\n'
        'fig.write_html(str(chart_path), include_plotlyjs="inline")\n'
        "\n"
        "RESULT = {\n"
        '    "sql": sql,\n'
        '    "chart_path": str(chart_path),\n'
        '    "dataframe_preview": df.head(20).to_dict(orient="records"),\n'
        '    "row_count": len(df),\n'
        '    "chart_type": "line",\n'
        "}\n"
    )


_ROUTER_SIMPLE = (
    '{"complexity": "simple", "selected_model": "gpt-4o-mini", '
    '"rationale": "Single table aggregation."}'
)
_ROUTER_COMPLEX = (
    '{"complexity": "complex", "selected_model": "gpt-4o", '
    '"rationale": "Joins and distinct counting required."}'
)
_ROUTER_UNSUPPORTED = (
    '{"complexity": "unsupported", "selected_model": null, '
    '"rationale": "Question references metric (price) not in the published catalog."}'
)
_ROUTER_CLARIFICATION = (
    '{"complexity": "clarification_needed", "selected_model": null, '
    '"rationale": "Ambiguous metric — needs user to specify what \\"best\\" means."}'
)


_PLAN_BY_DECADE = """{
  "analysis_intent": "trend",
  "tables": ["release_unique_view"],
  "dimensions": ["decade"],
  "metrics": [{"name": "releases", "aggregation": "count", "column": "*"}],
  "filters": [{"column": "decade", "operator": "IS NOT NULL", "value": null}],
  "chart_type": "bar",
  "notes": "Use release_unique_view (release-grain) for release counts."
}"""

_CODE_BY_DECADE = '''import duckdb
import pandas as pd
import plotly.express as px
from pathlib import Path
import os

DB_PATH = os.environ["ANALYTICS_DUCKDB_PATH"]
ARTIFACT_DIR = Path(os.environ["ARTIFACT_DIR"])
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(DB_PATH, read_only=True, config={"temp_directory": "/tmp/duckdb"})

sql = """
SELECT decade, COUNT(*) AS releases
FROM release_unique_view
WHERE decade IS NOT NULL
GROUP BY decade
ORDER BY decade
"""

df = con.execute(sql).df()

fig = px.bar(df, x="decade", y="releases", title="Releases by decade")
chart_path = ARTIFACT_DIR / "chart.html"
fig.write_html(str(chart_path), include_plotlyjs="inline")

RESULT = {
    "sql": sql,
    "chart_path": str(chart_path),
    "dataframe_preview": df.head(20).to_dict(orient="records"),
    "row_count": len(df),
    "chart_type": "bar",
}
'''


# Expose the canned codegen strings so tests can match on them.
CODE_BY_DECADE = _CODE_BY_DECADE
