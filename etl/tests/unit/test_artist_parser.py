"""Unit tests for ArtistStream (Fase 4)."""
from __future__ import annotations

from pathlib import Path

import pytest

from discogs_etl.parsers.artists_parser import ArtistStream, TruncationInfo


_FULL = """<artist>
  <id>10001</id>
  <name>Artist Alpha</name>
  <realname>Real Alpha</realname>
  <profile>Short bio.</profile>
</artist>
"""

_NO_REALNAME = """<artist>
  <id>10002</id>
  <name>Artist Bravo</name>
</artist>
"""

_NESTED = """<artist>
  <id>10003</id>
  <name>Artist Charlie</name>
  <realname>Real Charlie</realname>
  <namevariations>
    <name>ArtC</name>
  </namevariations>
  <aliases>
    <name id="50001">Alias One</name>
    <name id="50002">Alias Two</name>
  </aliases>
  <members>
    <name id="50003">Member One</name>
  </members>
</artist>
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_full_artist_record(tmp_path: Path):
    p = tmp_path / "ok.xml"
    _write(p, "<?xml version='1.0'?>\n<artists>\n" + _FULL + "</artists>\n")
    records = list(ArtistStream(p))
    assert len(records) == 1
    r = records[0]
    assert r["artist_id_raw"] == "10001"
    assert r["artist_name"] == "Artist Alpha"
    assert r["realname"] == "Real Alpha"
    assert r["profile"] == "Short bio."


def test_no_realname_no_profile(tmp_path: Path):
    p = tmp_path / "minimal.xml"
    _write(p, "<?xml version='1.0'?>\n<artists>\n" + _NO_REALNAME + "</artists>\n")
    records = list(ArtistStream(p))
    assert len(records) == 1
    r = records[0]
    assert r["realname"] is None
    assert r["profile"] is None


def test_nested_blocks_tolerated_but_not_extracted(tmp_path: Path):
    """Per Q1=B, the parser must handle nested aliases/members/groups
    without raising and without surfacing their contents in the record."""
    p = tmp_path / "nested.xml"
    _write(p, "<?xml version='1.0'?>\n<artists>\n" + _NESTED + "</artists>\n")
    records = list(ArtistStream(p))
    # Top-level <artist> emitted; nested <name id="..."> elements are NOT
    # emitted as separate artists (tag="artist" only matches <artist>).
    assert len(records) == 1
    r = records[0]
    assert r["artist_id_raw"] == "10003"
    assert "alias" not in r  # No alias fields surfaced.
    assert "members" not in r


def test_truncated_xml_stops_cleanly(tmp_path: Path):
    p = tmp_path / "trunc.xml"
    _write(p, "<?xml version='1.0'?>\n<artists>\n"
              + _FULL + _NO_REALNAME
              + "<artist><id>10099</id><name>Cut sho")
    stream = ArtistStream(p)
    records = list(stream)
    assert len(records) == 2
    assert isinstance(stream.truncation_info, TruncationInfo)
    assert stream.truncation_info.last_artist_id == 10002


def test_unicode_round_trip(tmp_path: Path):
    """Unicode in <name> and <realname> must round-trip."""
    p = tmp_path / "uni.xml"
    _write(p, "<?xml version='1.0'?>\n<artists>\n"
              "<artist><id>10010</id><name>Sigur Rós</name>"
              "<realname>Iceland Band</realname></artist>\n"
              "</artists>\n")
    records = list(ArtistStream(p))
    assert len(records) == 1
    assert records[0]["artist_name"] == "Sigur Rós"
