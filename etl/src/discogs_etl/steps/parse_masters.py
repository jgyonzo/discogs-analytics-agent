"""Step (Fase 4) — Parse masters.xml in streaming mode and write stg_masters.

Conditional step per spec ``003-masters-artists`` / ``research.md`` R-03:
when ``masters.xml(.gz)`` is missing from the snapshot dir, this step
returns early (no staging output, no error).
"""
from __future__ import annotations

from ..io import schemas
from ..io.input import open_masters_input
from ..io.parquet_writer import BatchedParquetWriter
from ..parsers.masters_parser import MasterStream
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..pipeline.progress import ProgressReporter
from ..transforms.text_normalization import clean_int


class ParseMastersStep:
    name = "parse_masters"

    def __init__(self, *, limit_masters: int | None = None) -> None:
        self.limit_masters = limit_masters

    def _output(self, ctx: RunContext):
        return ctx.staging_dir / "stg_masters.parquet"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return self._output(ctx).exists()

    def delete_outputs(self, ctx: RunContext) -> None:
        p = self._output(ctx)
        if p.exists():
            p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        log = ctx.logger
        # Conditional: skip if masters.xml(.gz) is missing.
        try:
            xi = open_masters_input(ctx.raw_snapshot_dir)
        except FileNotFoundError:
            log.info("parse_masters: masters input absent; skipping")
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

        with BatchedParquetWriter(out, schemas.STG_MASTERS, batch_size=batch_size) as w:
            reporter = ProgressReporter(log, self.name, progress_every)
            stream = MasterStream(ctx.raw_snapshot_dir, limit=self.limit_masters)
            for record in stream:
                n_in += 1
                mid = clean_int(record["master_id_raw"])
                if mid is None:
                    n_dropped += 1
                    continue
                w.write({
                    "master_id": mid,
                    "title": record["title"],
                    "main_release_id": clean_int(record["main_release_id_raw"]),
                    "year_raw": record["year_raw"],
                    "run_id": run_id,
                })
                n_emitted += 1
                reporter.report_iteration(n_emitted)

            metrics = reporter.final()
            row_count = w.row_count

        manifest.record_output("staging", "stg_masters", path=out, row_count=row_count)
        manifest.record_step_metrics(
            self.name, releases_per_sec=metrics.releases_per_sec,
        )

        if n_dropped > 0:
            manifest.warn(
                "parse_masters.dropped_no_master_id",
                f"{n_dropped} of {n_in} <master> elements had no parseable id; dropped",
            )
        if stream.truncation_info is not None:
            info = stream.truncation_info
            manifest.warn(
                "parse_masters.truncated_xml",
                f"last_master_id={info.last_master_id}; error={info.error_message}",
            )
            log.warning(
                "parse_masters: truncated after master_id=%s; %s",
                info.last_master_id, info.error_message,
            )

        log.info(
            "parse_masters done: in=%d emitted=%d dropped=%d truncated=%s",
            n_in, n_emitted, n_dropped, stream.truncation_info is not None,
        )
