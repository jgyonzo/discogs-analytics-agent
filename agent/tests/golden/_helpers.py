"""Shared helpers for golden-query tests.

Wraps a canonical SQL string into a sandbox-runnable Python
program — same shape as the stub's ``_CODE_BY_DECADE`` template.
Tests register the wrapped code via ``stub_module.set_responses``
keyed on ``(node_name, query_hash)``.
"""

from __future__ import annotations


def wrap_sandbox_code(sql: str, *, chart_type: str, plotly_call: str) -> str:
    """Build a sandbox script that runs ``sql`` against the read-only
    DuckDB and writes a Plotly HTML artifact.

    `plotly_call` should reference ``df`` and produce a ``fig`` —
    e.g. ``px.bar(df, x="decade", y="releases")``.
    """
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
        f'sql = """{sql}"""\n'
        "\n"
        "df = con.execute(sql).df()\n"
        "\n"
        f"fig = {plotly_call}\n"
        'chart_path = ARTIFACT_DIR / "chart.html"\n'
        'fig.write_html(str(chart_path), include_plotlyjs="inline")\n'
        "\n"
        "RESULT = {\n"
        '    "sql": sql,\n'
        '    "chart_path": str(chart_path),\n'
        '    "dataframe_preview": df.head(20).to_dict(orient="records"),\n'
        '    "row_count": len(df),\n'
        f'    "chart_type": "{chart_type}",\n'
        "}\n"
    )
