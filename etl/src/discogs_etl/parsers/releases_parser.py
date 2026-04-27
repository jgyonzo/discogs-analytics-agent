"""Streaming Discogs releases.xml parser.

Yields one structured dict per ``<release>`` element. Memory-bounded via the
canonical lxml iterparse + clear() + walk-back-siblings idiom.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from lxml import etree


def iter_releases(
    path: str | Path,
    *,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream releases from a Discogs releases.xml file.

    Each yielded dict has keys: ``release``, ``artists``, ``labels``,
    ``formats``, ``format_descriptions``, ``genres``, ``styles``,
    ``tracks``. ``release`` is a single dict; the rest are lists of dicts
    in XML document order. Field values are raw text (or attribute values)
    — no normalization is performed here. Subsequent clean steps apply
    text/date/format normalization.
    """
    p = str(path)
    parsed_at = datetime.now(timezone.utc)
    n_emitted = 0

    context = etree.iterparse(p, events=("end",), tag="release")
    for _event, elem in context:
        try:
            yield _release_to_record(elem, parsed_at)
            n_emitted += 1
        finally:
            elem.clear()
            parent = elem.getparent()
            while elem.getprevious() is not None:
                if parent is None:
                    break
                del parent[0]
        if limit is not None and n_emitted >= limit:
            break

    del context


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
