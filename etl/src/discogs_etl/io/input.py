"""Gzip-aware input opener for Discogs XML files.

Generalized in Fase 4 (spec ``003-masters-artists`` / ``research.md``
R-01) to take a basename so the same detection / precedence logic
applies to ``releases.xml``, ``masters.xml``, and ``artists.xml``.

Per spec ``002-etl-scaleup`` / ``research.md`` R-02 (preserved):
- If both ``{basename}.xml`` and ``{basename}.xml.gz`` exist, the
  uncompressed file wins and the caller is notified via
  ``gz_and_plain_present=True``.
- Detection is suffix-based; no magic-byte sniffing.
- Decompression is streaming (``gzip.GzipFile`` reads in chunks).

Wrapper functions ``open_releases_input``, ``open_masters_input``,
``open_artists_input`` preserve the per-input call sites used by
parsers and steps.
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass
class XmlInput:
    """Result of resolving an XML input in a snapshot directory."""
    file_obj: BinaryIO
    source_path: Path
    is_gzipped: bool
    gz_and_plain_present: bool


# Backward-compatible alias for the Fase 1+2+3 type name.
ReleasesInput = XmlInput


def open_xml_input(snapshot_dir: str | Path, basename: str) -> XmlInput:
    """Resolve and open ``{basename}.xml(.gz)`` for a snapshot directory.

    Looks for ``{basename}.xml`` first; falls back to ``{basename}.xml.gz``.
    Raises FileNotFoundError if neither is present.
    """
    snap = Path(snapshot_dir)
    plain = snap / f"{basename}.xml"
    gz = snap / f"{basename}.xml.gz"

    if plain.exists():
        return XmlInput(
            file_obj=plain.open("rb"),
            source_path=plain,
            is_gzipped=False,
            gz_and_plain_present=gz.exists(),
        )
    if gz.exists():
        return XmlInput(
            file_obj=gzip.GzipFile(filename=str(gz), mode="rb"),
            source_path=gz,
            is_gzipped=True,
            gz_and_plain_present=False,
        )
    raise FileNotFoundError(
        f"no {basename}.xml or {basename}.xml.gz found in {snap}"
    )


def open_releases_input(snapshot_dir: str | Path) -> XmlInput:
    """Resolve and open the releases XML for a snapshot directory."""
    return open_xml_input(snapshot_dir, "releases")


def open_masters_input(snapshot_dir: str | Path) -> XmlInput:
    """Resolve and open the masters XML for a snapshot directory (Fase 4)."""
    return open_xml_input(snapshot_dir, "masters")


def open_artists_input(snapshot_dir: str | Path) -> XmlInput:
    """Resolve and open the artists XML for a snapshot directory (Fase 4)."""
    return open_xml_input(snapshot_dir, "artists")


def resolve_xml_input(path: str | Path, basename: str) -> BinaryIO:
    """Resolve a parser input path into an open binary file-object.

    Generalized over the per-parser ``_resolve_input`` helpers so all
    three parsers (releases / masters / artists) can share the same
    flexibility:

    - a directory containing ``{basename}.xml(.gz)`` →
      :func:`open_xml_input`;
    - a file path that exists → opens directly (gzip-decoded if ``.gz``);
    - a non-existent path whose parent directory exists →
      :func:`open_xml_input` against the parent.
    """
    p = Path(path)
    if p.is_dir():
        return open_xml_input(p, basename).file_obj
    if p.is_file():
        if p.suffix == ".gz":
            return gzip.GzipFile(filename=str(p), mode="rb")
        return open(p, "rb")
    if p.parent.is_dir():
        return open_xml_input(p.parent, basename).file_obj
    raise FileNotFoundError(f"no {basename} input at {p}")
