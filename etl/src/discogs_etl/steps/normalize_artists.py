"""Step (Fase 4) — Normalize artists: text-normalize and pass through.

Conditional step per ``research.md`` R-03: skips when
``stg_artists.parquet`` is absent.

Per Q1=B / spec ``003-masters-artists`` FR-008, ``clean_artists`` is
a passthrough of ``stg_artists`` with text-normalization on
``artist_name`` / ``realname`` / ``profile``. No nested
alias/group/member counts in this spec.

Side effect: scans the (already-produced) ``release_artist_bridge.parquet``
to detect artist_ids referenced by the bridge but absent from
``clean_artists``. Non-zero count → emits a manifest warning per FR-015.
"""
from __future__ import annotations

import pyarrow.parquet as pq

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..transforms.text_normalization import clean_text


class NormalizeArtistsStep:
    name = "normalize_artists"

    def _input(self, ctx: RunContext):
        return ctx.staging_dir / "stg_artists.parquet"

    def _output(self, ctx: RunContext):
        return ctx.clean_dir / "clean_artists.parquet"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return self._output(ctx).exists()

    def delete_outputs(self, ctx: RunContext) -> None:
        p = self._output(ctx)
        if p.exists():
            p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        stg = self._input(ctx)
        if not stg.exists():
            ctx.logger.info(
                "normalize_artists: %s absent (parse_artists skipped); skipping",
                stg,
            )
            return

        ctx.clean_dir.mkdir(parents=True, exist_ok=True)
        out = self._output(ctx)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size

        clean_artist_ids: set[int] = set()
        with BatchedParquetWriter(out, schemas.CLEAN_ARTISTS, batch_size=batch_size) as w:
            for row in pq.read_table(stg).to_pylist():
                aid = row["artist_id"]
                clean_artist_ids.add(aid)
                w.write({
                    "artist_id": aid,
                    "artist_name": clean_text(row["artist_name"]),
                    "realname": clean_text(row["realname"]),
                    "profile": clean_text(row["profile"]),
                    "run_id": run_id,
                })
            row_count = w.row_count

        manifest.record_output(
            "clean", "clean_artists", path=out, row_count=row_count,
        )

        # Cross-check: artist_ids referenced by release_artist_bridge but
        # absent from clean_artists.
        bridge = ctx.analytics_dir / "release_artist_bridge.parquet"
        if bridge.exists():
            bridge_ids = {
                v for v in pq.read_table(bridge).column("artist_id").to_pylist()
                if v is not None
            }
            unresolved = bridge_ids - clean_artist_ids
            if unresolved:
                manifest.warn(
                    "normalize_artists.bridge_unresolved_artists",
                    f"{len(unresolved)} artist_id(s) in release_artist_bridge "
                    f"are absent from clean_artists; e.g. {sorted(unresolved)[:5]}",
                )
