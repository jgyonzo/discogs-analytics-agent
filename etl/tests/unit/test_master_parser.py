"""Unit tests for MasterStream (Fase 4)."""
from __future__ import annotations

from pathlib import Path

import pytest

from discogs_etl.parsers.masters_parser import MasterStream, TruncationInfo


_GOOD_MASTER = """<master id="42">
  <main_release>1001</main_release>
  <title>Test Master Alpha</title>
  <year>2010</year>
  <data_quality>Correct</data_quality>
</master>
"""

_GOOD_MASTER_2 = """<master id="43">
  <title>Test Master Bravo</title>
  <year>2011</year>
</master>
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_clean_xml_yields_records_no_truncation(tmp_path: Path):
    p = tmp_path / "ok.xml"
    _write(p, "<?xml version='1.0'?>\n<masters>\n"
              + _GOOD_MASTER + _GOOD_MASTER_2 + "</masters>\n")
    stream = MasterStream(p)
    records = list(stream)
    assert len(records) == 2
    assert stream.truncation_info is None
    assert records[0]["master_id_raw"] == "42"
    assert records[0]["title"] == "Test Master Alpha"
    assert records[0]["main_release_id_raw"] == "1001"
    assert records[0]["year_raw"] == "2010"
    # 43 has no main_release.
    assert records[1]["main_release_id_raw"] is None


def test_truncated_xml_stops_cleanly(tmp_path: Path):
    p = tmp_path / "trunc.xml"
    _write(p, "<?xml version='1.0'?>\n<masters>\n"
              + _GOOD_MASTER + _GOOD_MASTER_2
              + '<master id="44"><title>Cut sho')
    stream = MasterStream(p)
    records = list(stream)
    assert len(records) == 2
    assert isinstance(stream.truncation_info, TruncationInfo)
    assert stream.truncation_info.last_master_id == 43


def test_iter_masters_wrapper_returns_iterable(tmp_path: Path):
    from discogs_etl.parsers.masters_parser import iter_masters
    p = tmp_path / "wrap.xml"
    _write(p, "<?xml version='1.0'?>\n<masters>\n" + _GOOD_MASTER + "</masters>\n")
    records = list(iter_masters(p))
    assert len(records) == 1
    assert records[0]["master_id_raw"] == "42"
