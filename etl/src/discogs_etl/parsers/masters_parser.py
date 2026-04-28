"""Streaming Discogs masters.xml parser.

Yields one structured dict per ``<master>`` element. Mirrors the
:class:`discogs_etl.parsers.releases_parser.ReleaseStream` pattern:
``lxml.iterparse`` + ``clear()`` + walk-back-siblings for bounded
memory; ``try / except etree.XMLSyntaxError`` for graceful
truncation handling.

Per spec ``003-masters-artists`` / ``research.md`` R-02. Only the
top-level fields documented in source spec §6.9 are extracted:
``master_id`` (the ``id`` attribute), ``title``, ``main_release``,
``year``. Nested ``<artists>`` / ``<genres>`` / ``<styles>`` /
``<videos>`` elements are visited only enough for lxml to advance.
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
    last_master_id: int | None
    error_message: str


class MasterStream:
    """Iterable streaming parser for Discogs masters XML."""

    def __init__(self, path: str | Path, *, limit: int | None = None) -> None:
        self.path = path
        self.limit = limit
        self.truncation_info: TruncationInfo | None = None
        self._n_emitted = 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._iterate()

    def _iterate(self) -> Iterator[dict[str, Any]]:
        parsed_at = datetime.now(timezone.utc)
        last_master_id: int | None = None
        file_obj = resolve_xml_input(Path(self.path), "masters")

        try:
            context = etree.iterparse(file_obj, events=("end",), tag="master")
            for _event, elem in context:
                try:
                    record = _master_to_record(elem, parsed_at)
                    rid_raw = record["master_id_raw"]
                    if rid_raw is not None:
                        try:
                            last_master_id = int(rid_raw)
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
                last_master_id=last_master_id,
                error_message=str(e)[:200],
            )
        finally:
            try:
                file_obj.close()
            except Exception:  # noqa: BLE001
                pass


def iter_masters(
    path: str | Path,
    *,
    limit: int | None = None,
) -> MasterStream:
    """Backward-compatible wrapper returning an iterable MasterStream."""
    return MasterStream(path, limit=limit)


def _txt(el) -> str | None:
    if el is None or el.text is None:
        return None
    s = el.text.strip()
    return s if s else None


def _master_to_record(elem, parsed_at: datetime) -> dict[str, Any]:
    """Extract the §6.9 fields from a single ``<master>`` element."""
    return {
        "master_id_raw": elem.get("id"),
        "title": _txt(elem.find("title")),
        "main_release_id_raw": _txt(elem.find("main_release")),
        "year_raw": _txt(elem.find("year")),
        "parsed_at": parsed_at,
    }
