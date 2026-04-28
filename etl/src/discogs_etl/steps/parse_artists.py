"""Step (Fase 4) — Parse artists.xml in streaming mode and write stg_artists.

Conditional step per spec ``003-masters-artists`` / ``research.md`` R-03:
when ``artists.xml(.gz)`` is missing from the snapshot dir, this step
returns early (no staging output, no error).
"""
from __future__ import annotations

from ..io import schemas
from ..io.input import open_artists_input
from ..io.parquet_writer import BatchedParquetWriter
from ..parsers.artists_parser import ArtistStream
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..pipeline.progress import ProgressReporter
from ..transforms.text_normalization import clean_int


class ParseArtistsStep:
    name = "parse_artists"

    def __init__(self, *, limit_artists: int | None = None) -> None:
        self.limit_artists = limit_artists

    def _output(self, ctx: RunContext):
        return ctx.staging_dir / "stg_artists.parquet"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return self._output(ctx).exists()

    def delete_outputs(self, ctx: RunContext) -> None:
        p = self._output(ctx)
        if p.exists():
            p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        log = ctx.logger
        try:
            xi = open_artists_input(ctx.raw_snapshot_dir)
        except FileNotFoundError:
            log.info("parse_artists: artists input absent; skipping")
            return
        try:
            xi.file_obj.close()
        except Exception:  # noqa: BLE001
            pass

        ctx.staging_dir.mkdir(parents=True, exist_ok=True)
        out = self._output(ctx)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size
        progress_every = max(1, ctx.config.limits.log_progress_every)

        n_in = 0
        n_emitted = 0
        n_dropped = 0

        with BatchedParquetWriter(out, schemas.STG_ARTISTS, batch_size=batch_size) as w:
            reporter = ProgressReporter(log, self.name, progress_every)
            stream = ArtistStream(ctx.raw_snapshot_dir, limit=self.limit_artists)
            for record in stream:
                n_in += 1
                aid = clean_int(record["artist_id_raw"])
                if aid is None:
                    n_dropped += 1
                    continue
                w.write({
                    "artist_id": aid,
                    "artist_name": record["artist_name"],
                    "realname": record["realname"],
                    "profile": record["profile"],
                    "run_id": run_id,
                })
                n_emitted += 1
                reporter.report_iteration(n_emitted)

            metrics = reporter.final()
            row_count = w.row_count

        manifest.record_output("staging", "stg_artists", path=out, row_count=row_count)
        manifest.record_step_metrics(
            self.name, releases_per_sec=metrics.releases_per_sec,
        )

        if n_dropped > 0:
            manifest.warn(
                "parse_artists.dropped_no_artist_id",
                f"{n_dropped} of {n_in} <artist> elements had no parseable id; dropped",
            )
        if stream.truncation_info is not None:
            info = stream.truncation_info
            manifest.warn(
                "parse_artists.truncated_xml",
                f"last_artist_id={info.last_artist_id}; error={info.error_message}",
            )
            log.warning(
                "parse_artists: truncated after artist_id=%s; %s",
                info.last_artist_id, info.error_message,
            )

        log.info(
            "parse_artists done: in=%d emitted=%d dropped=%d truncated=%s",
            n_in, n_emitted, n_dropped, stream.truncation_info is not None,
        )
