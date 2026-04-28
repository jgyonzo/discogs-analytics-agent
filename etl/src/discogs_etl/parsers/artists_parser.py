"""Streaming Discogs artists.xml parser.

Yields one structured dict per ``<artist>`` element. Mirrors the
:class:`discogs_etl.parsers.releases_parser.ReleaseStream` pattern:
``lxml.iterparse`` + ``clear()`` + walk-back-siblings for bounded
memory; ``try / except etree.XMLSyntaxError`` for graceful
truncation handling.

Per spec ``003-masters-artists`` / ``research.md`` R-02 / R-07.
Only the top-level fields documented in source spec §6.10 are
extracted: ``artist_id`` (the ``<id>`` *child element*, not an
attribute — Discogs artists XML differs from releases / masters
in this respect), ``artist_name``, ``realname``, ``profile``.
Nested ``<aliases>`` / ``<members>`` / ``<groups>`` /
``<urls>`` / ``<namevariations>`` blocks are visited only enough
for lxml to advance; their contents are NOT extracted in this
spec (Q1=B; ``artist_dim`` is deferred to a future spec).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from lxml import etree

from ..io.input import resolve_xml_input


@dataclass
class TruncationInfo:
    """Captured when iterparse fails after a partial parse."""
    last_artist_id: int | None
    error_message: str


class ArtistStream:
    """Iterable streaming parser for Discogs artists XML."""

    def __init__(self, path: str | Path, *, limit: int | None = None) -> None:
        self.path = path
        self.limit = limit
        self.truncation_info: TruncationInfo | None = None
        self._n_emitted = 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._iterate()

    def _iterate(self) -> Iterator[dict[str, Any]]:
        parsed_at = datetime.now(timezone.utc)
        last_artist_id: int | None = None
        file_obj = resolve_xml_input(Path(self.path), "artists")

        try:
            context = etree.iterparse(file_obj, events=("end",), tag="artist")
            for _event, elem in context:
                # Artist elements appear nested inside <aliases> / <members> /
                # <groups> as <name id=...> tags too. We only care about
                # *top-level* <artist> elements (direct children of <artists>).
                # lxml.iterparse with tag="artist" matches every <artist>
                # element regardless of depth, but Discogs artists.xml uses
                # <name id=N> inside the nested blocks (NOT <artist>), so the
                # tag filter is safe.
                try:
                    record = _artist_to_record(elem, parsed_at)
                    rid_raw = record["artist_id_raw"]
                    if rid_raw is not None:
                        try:
                            last_artist_id = int(rid_raw)
                        except (TypeError, ValueError):
                            pass
                    yield record
                    self._n_emitted += 1
                finally:
                    elem.clear()
                    parent = elem.getparent()
                    while elem.getprevious() is not None:
                        if parent is None:
                            break
                        del parent[0]
                if self.limit is not None and self._n_emitted >= self.limit:
                    break
        except etree.XMLSyntaxError as e:
            self.truncation_info = TruncationInfo(
                last_artist_id=last_artist_id,
                error_message=str(e)[:200],
            )
        finally:
            try:
                file_obj.close()
            except Exception:  # noqa: BLE001
                pass


def iter_artists(
    path: str | Path,
    *,
    limit: int | None = None,
) -> ArtistStream:
    """Backward-compatible wrapper returning an iterable ArtistStream."""
    return ArtistStream(path, limit=limit)


def _txt(el) -> str | None:
    if el is None or el.text is None:
        return None
    s = el.text.strip()
    return s if s else None


def _artist_to_record(elem, parsed_at: datetime) -> dict[str, Any]:
    """Extract the §6.10 fields from a single ``<artist>`` element."""
    return {
        "artist_id_raw": _txt(elem.find("id")),
        "artist_name": _txt(elem.find("name")),
        "realname": _txt(elem.find("realname")),
        "profile": _txt(elem.find("profile")),
        "parsed_at": parsed_at,
    }
