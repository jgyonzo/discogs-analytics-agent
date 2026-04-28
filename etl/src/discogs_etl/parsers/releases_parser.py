"""Streaming Discogs releases.xml parser.

Yields one structured dict per ``<release>`` element. Memory-bounded via the
canonical lxml iterparse + clear() + walk-back-siblings idiom.

Per spec ``002-etl-scaleup`` (Fase 2 robustness, FR-001/FR-002), a
truncated XML stream that fails ``lxml.iterparse`` *after* at least one
fully-formed release has been emitted does NOT propagate the
``XMLSyntaxError`` to the runner. Instead the stream stops cleanly and
exposes ``ReleaseStream.truncation_info`` for the caller to surface as
a manifest warning.
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from lxml import etree

from ..io.input import resolve_xml_input


@dataclass
class TruncationInfo:
    """Metadata captured when iterparse fails after a partial parse."""
    last_release_id: int | None
    error_message: str


class ReleaseStream:
    """Iterable streaming parser for Discogs releases XML.

    Construct once, then iterate; after iteration ends, inspect
    ``.truncation_info`` (None on a clean parse, populated on a
    mid-stream parse error). Memory bound is preserved across the
    truncation-handling path.
    """

    def __init__(self, path: str | Path, *, limit: int | None = None) -> None:
        self.path = path
        self.limit = limit
        self.truncation_info: TruncationInfo | None = None
        self._n_emitted = 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._iterate()

    def _iterate(self) -> Iterator[dict[str, Any]]:
        parsed_at = datetime.now(timezone.utc)
        last_release_id: int | None = None
        file_obj = resolve_xml_input(Path(self.path), "releases")

        try:
            context = etree.iterparse(file_obj, events=("end",), tag="release")
            for _event, elem in context:
                try:
                    record = _release_to_record(elem, parsed_at)
                    rid_raw = record["release"]["release_id_raw"]
                    if rid_raw is not None:
                        try:
                            last_release_id = int(rid_raw)
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
                last_release_id=last_release_id,
                error_message=str(e)[:200],
            )
        finally:
            try:
                file_obj.close()
            except Exception:  # noqa: BLE001 — close is best-effort
                pass


def iter_releases(
    path: str | Path,
    *,
    limit: int | None = None,
) -> ReleaseStream:
    """Backward-compatible wrapper that returns an iterable ReleaseStream.

    Existing callers using ``for record in iter_releases(...)`` keep
    working unchanged. New callers can use ``ReleaseStream`` directly
    and inspect ``.truncation_info`` after iteration.
    """
    return ReleaseStream(path, limit=limit)


def _txt(el) -> str | None:
    if el is None or el.text is None:
        return None
    s = el.text.strip()
    return s if s else None


def _release_to_record(elem, parsed_at: datetime) -> dict[str, Any]:
    videos_el = elem.find("videos")
    extraartists_el = elem.find("extraartists")
    rel: dict[str, Any] = {
        "release_id_raw": elem.get("id"),
        "title": _txt(elem.find("title")),
        "country": _txt(elem.find("country")),
        "released_raw": _txt(elem.find("released")),
        "notes": _txt(elem.find("notes")),
        "data_quality": _txt(elem.find("data_quality")),
        "status": elem.get("status"),
        "has_videos": videos_el is not None and len(videos_el) > 0,
        "has_extraartists": extraartists_el is not None and len(extraartists_el) > 0,
        "parsed_at": parsed_at,
    }
    master_id_el = elem.find("master_id")
    if master_id_el is not None:
        text = (master_id_el.text or "").strip() or None
        rel["master_id_raw"] = text
        rel["master_is_main_release_raw"] = master_id_el.get("is_main_release")
    else:
        rel["master_id_raw"] = None
        rel["master_is_main_release_raw"] = None

    artists: list[dict[str, Any]] = []
    artists_el = elem.find("artists")
    if artists_el is not None:
        for i, a in enumerate(artists_el.findall("artist"), start=1):
            artists.append({
                "artist_order": i,
                "artist_id_raw": _txt(a.find("id")),
                "artist_name": _txt(a.find("name")),
                "artist_anv": _txt(a.find("anv")),
                "artist_join": _txt(a.find("join")),
            })

    labels: list[dict[str, Any]] = []
    labels_el = elem.find("labels")
    if labels_el is not None:
        for i, l in enumerate(labels_el.findall("label"), start=1):
            labels.append({
                "label_order": i,
                "label_id_raw": l.get("id"),
                "label_name": l.get("name"),
                "catno": l.get("catno"),
            })

    formats: list[dict[str, Any]] = []
    format_descriptions: list[dict[str, Any]] = []
    formats_el = elem.find("formats")
    if formats_el is not None:
        for i, f in enumerate(formats_el.findall("format"), start=1):
            formats.append({
                "format_order": i,
                "format_name": f.get("name"),
                "format_qty_raw": f.get("qty"),
                "format_text": f.get("text"),
            })
            descs_el = f.find("descriptions")
            if descs_el is not None:
                for j, d in enumerate(descs_el.findall("description"), start=1):
                    format_descriptions.append({
                        "format_order": i,
                        "description_order": j,
                        "description": _txt(d),
                    })

    genres: list[dict[str, Any]] = []
    genres_el = elem.find("genres")
    if genres_el is not None:
        for i, g in enumerate(genres_el.findall("genre"), start=1):
            genres.append({"genre_order": i, "genre": _txt(g)})

    styles: list[dict[str, Any]] = []
    styles_el = elem.find("styles")
    if styles_el is not None:
        for i, s in enumerate(styles_el.findall("style"), start=1):
            styles.append({"style_order": i, "style": _txt(s)})

    tracks: list[dict[str, Any]] = []
    tl_el = elem.find("tracklist")
    if tl_el is not None:
        for i, t in enumerate(tl_el.findall("track"), start=1):
            tracks.append({
                "track_order": i,
                "position": _txt(t.find("position")),
                "title": _txt(t.find("title")),
                "duration_raw": _txt(t.find("duration")),
                "track_type": _txt(t.find("type_")) or t.get("type"),
            })

    return {
        "release": rel,
        "artists": artists,
        "labels": labels,
        "formats": formats,
        "format_descriptions": format_descriptions,
        "genres": genres,
        "styles": styles,
        "tracks": tracks,
    }
