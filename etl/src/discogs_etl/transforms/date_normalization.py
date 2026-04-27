"""Date normalization per source spec §11.1."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

DatePrecision = Literal["day", "month", "year", "unknown", "invalid"]

VALID_PRECISIONS: frozenset[str] = frozenset({"day", "month", "year", "unknown", "invalid"})

_FULL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR_ONLY = re.compile(r"^(\d{4})$")

_YEAR_MIN = 1850


def _year_max() -> int:
    return datetime.now(timezone.utc).year + 1


def _decade(year: int | None) -> int | None:
    return (year // 10) * 10 if year is not None else None


def _year_in_range(year: int) -> bool:
    return _YEAR_MIN <= year <= _year_max()


@dataclass(frozen=True)
class ParsedDate:
    year: int | None
    month: int | None
    day: int | None
    released_date: date | None
    released_date_precision: DatePrecision
    decade: int | None


_UNKNOWN = ParsedDate(None, None, None, None, "unknown", None)
_INVALID = ParsedDate(None, None, None, None, "invalid", None)


def parse_released(raw: str | None) -> ParsedDate:
    """Map a Discogs ``released`` string onto the §11.1 normalized fields."""
    if raw is None:
        return _UNKNOWN
    s = raw.strip()
    if not s:
        return _UNKNOWN
    low = s.lower()
    if low == "unknown" or s in ("0000", "0000-00-00", "0000-00", "0"):
        return _UNKNOWN

    m = _FULL.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y == 0 or not _year_in_range(y):
            return _INVALID
        if d == 0:
            if 1 <= mo <= 12:
                return ParsedDate(y, mo, None, date(y, mo, 1), "month", _decade(y))
            return _INVALID
        try:
            return ParsedDate(y, mo, d, date(y, mo, d), "day", _decade(y))
        except ValueError:
            return _INVALID

    m = _YEAR_MONTH.match(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if y == 0 or not _year_in_range(y) or not (1 <= mo <= 12):
            return _INVALID
        return ParsedDate(y, mo, None, date(y, mo, 1), "month", _decade(y))

    m = _YEAR_ONLY.match(s)
    if m:
        y = int(m.group(1))
        if y == 0:
            return _UNKNOWN
        if not _year_in_range(y):
            return _INVALID
        return ParsedDate(y, None, None, date(y, 1, 1), "year", _decade(y))

    return _INVALID
