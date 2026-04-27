"""Trim/empty-to-null helpers for staging→clean conversions."""
from __future__ import annotations


def clean_text(value: str | None) -> str | None:
    """Strip whitespace; empty becomes None."""
    if value is None:
        return None
    s = value.strip()
    return s if s else None


def clean_int(value: str | None) -> int | None:
    """Parse int; empty / non-numeric / None all become None."""
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def clean_bool_attr(value: str | None) -> bool | None:
    """Parse XML boolean-like attribute values: true/1/yes vs false/0/no."""
    if value is None:
        return None
    s = value.strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None
