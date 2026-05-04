"""Helpers for parsing LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(?P<body>.*?)\n?```\s*$",
    re.DOTALL,
)


def parse_json_response(content: str) -> Any:
    """json.loads, but tolerant of ```json ... ``` fences that chat
    models often emit even when the prompt asks for raw JSON."""
    text = content.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group("body").strip()
    return json.loads(text)
