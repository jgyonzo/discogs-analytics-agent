"""Unit tests for date normalization (source spec §11.1)."""
from __future__ import annotations

from datetime import date

import pytest

from discogs_etl.transforms.date_normalization import parse_released


def test_full_date_day_precision():
    p = parse_released("1999-07-13")
    assert (p.year, p.month, p.day) == (1999, 7, 13)
    assert p.released_date == date(1999, 7, 13)
    assert p.released_date_precision == "day"
    assert p.decade == 1990


def test_partial_yyyy_mm_00_is_month_precision():
    p = parse_released("1998-06-00")
    assert p.year == 1998
    assert p.month == 6
    assert p.day is None
    assert p.released_date == date(1998, 6, 1)
    assert p.released_date_precision == "month"
    assert p.decade == 1990


def test_year_only():
    p = parse_released("1985")
    assert p.year == 1985
    assert p.month is None
    assert p.day is None
    assert p.released_date == date(1985, 1, 1)
    assert p.released_date_precision == "year"
    assert p.decade == 1980


@pytest.mark.parametrize("raw", ["", "  ", "Unknown", "unknown", "0000", "0000-00-00", None])
def test_unknown_inputs(raw):
    p = parse_released(raw)
    assert p.released_date_precision == "unknown"
    assert p.year is None and p.month is None and p.day is None
    assert p.released_date is None
    assert p.decade is None


@pytest.mark.parametrize("raw", ["not-a-date", "1999-13-01", "1999-02-30"])
def test_invalid_inputs(raw):
    p = parse_released(raw)
    assert p.released_date_precision == "invalid"


def test_year_below_min_is_invalid():
    p = parse_released("1700-01-01")
    assert p.released_date_precision == "invalid"


def test_yyyy_mm_form():
    p = parse_released("2001-09")
    assert p.released_date_precision == "month"
    assert p.released_date == date(2001, 9, 1)
    assert p.year == 2001 and p.month == 9 and p.day is None


def test_decade_derivation():
    assert parse_released("2003-05-12").decade == 2000
    assert parse_released("1999-12-31").decade == 1990
    assert parse_released("2010-01-01").decade == 2010
