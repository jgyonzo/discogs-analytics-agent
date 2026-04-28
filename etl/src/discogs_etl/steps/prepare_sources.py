"""Step 1 — Prepare sources: resolve releases / masters / artists XML inputs.

Per spec ``002-etl-scaleup`` (FR-010): the input may be either an
uncompressed ``releases.xml`` or a gzipped ``releases.xml.gz``.

Per spec ``003-masters-artists`` (FR-002): masters and artists XMLs
are *optional* — missing inputs emit warnings and the corresponding
parse / normalize / build steps return early. Only ``releases.xml``
remains required.
"""
from __future__ import annotations

from ..io.file_utils import sha256_file
from ..io.input import (
    open_artists_input,
    open_masters_input,
    open_releases_input,
)
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class PrepareSourcesStep:
    name = "prepare_sources"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return False

    def delete_outputs(self, ctx: RunContext) -> None:
        pass

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        # Required: releases.
        try:
            ri = open_releases_input(ctx.raw_snapshot_dir)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"no releases input in snapshot dir {ctx.raw_snapshot_dir}"
            ) from e
        try:
            ri.file_obj.close()
        except Exception:  # noqa: BLE001
            pass
        self._record_input(manifest, "releases", ri, ctx)

        # Optional: masters (Fase 4).
        try:
            mi = open_masters_input(ctx.raw_snapshot_dir)
        except FileNotFoundError:
            manifest.warn(
                "prepare_sources.masters_missing",
                f"no masters.xml(.gz) in {ctx.raw_snapshot_dir}",
            )
        else:
            try:
                mi.file_obj.close()
            except Exception:  # noqa: BLE001
                pass
            self._record_input(manifest, "masters", mi, ctx)

        # Optional: artists (Fase 4).
        try:
            ai = open_artists_input(ctx.raw_snapshot_dir)
        except FileNotFoundError:
            manifest.warn(
                "prepare_sources.artists_missing",
                f"no artists.xml(.gz) in {ctx.raw_snapshot_dir}",
            )
        else:
            try:
                ai.file_obj.close()
            except Exception:  # noqa: BLE001
                pass
            self._record_input(manifest, "artists", ai, ctx)

    @staticmethod
    def _record_input(manifest, name, xi, ctx) -> None:
        path = xi.source_path
        size = path.stat().st_size
        ctx.logger.info(
            "prepare_sources: hashing %s (%d bytes; gzipped=%s)",
            path, size, xi.is_gzipped,
        )
        checksum = sha256_file(path)
        manifest.record_source_file(
            name, path=path, size_bytes=size, checksum=checksum,
        )
        if xi.is_gzipped:
            manifest.warn(f"prepare_sources.gz_input", f"{name}: {path}")
        if xi.gz_and_plain_present:
            manifest.warn(
                f"prepare_sources.gz_and_plain_present",
                f"{name}: using uncompressed {path}; .gz sibling also present",
            )
