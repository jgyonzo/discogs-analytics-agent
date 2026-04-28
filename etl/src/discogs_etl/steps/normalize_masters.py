"""Step (Fase 4) — Normalize masters: year_raw → year / decade / year_precision.

Conditional step per ``research.md`` R-03: skips when
``stg_masters.parquet`` is absent (cascade from
``parse_masters`` skipping when input was missing).

Year normalization reuses :func:`parse_released` per
``research.md`` R-06 — only the ``year`` / ``year_precision`` /
``decade`` outputs are propagated; month / day are discarded.
"""
from __future__ import annotations

import pyarrow.parquet as pq

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..transforms.date_normalization import parse_released
from ..transforms.text_normalization import clean_text


class NormalizeMastersStep:
    name = "normalize_masters"

    def _input(self, ctx: RunContext):
        return ctx.staging_dir / "stg_masters.parquet"

    def _output(self, ctx: RunContext):
        return ctx.clean_dir / "clean_masters.parquet"

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
                "normalize_masters: %s absent (parse_masters skipped); skipping",
                stg,
            )
            return

        ctx.clean_dir.mkdir(parents=True, exist_ok=True)
        out = self._output(ctx)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size

        n_invalid_years = 0
        with BatchedParquetWriter(out, schemas.CLEAN_MASTERS, batch_size=batch_size) as w:
            for row in pq.read_table(stg).to_pylist():
                pd = parse_released(row["year_raw"])
                # Only year / unknown / invalid are valid in this layer.
                if pd.released_date_precision in ("year", "unknown", "invalid"):
                    precision = pd.released_date_precision
                else:
                    # day / month inputs aren't expected for master year_raw;
                    # collapse to invalid to keep the enum tight.
                    precision = "invalid"
                if precision == "invalid":
                    n_invalid_years += 1
                w.write({
                    "master_id": row["master_id"],
                    "title": clean_text(row["title"]),
                    "main_release_id": row["main_release_id"],
                    "year": pd.year,
                    "decade": pd.decade,
                    "year_precision": precision,
                    "run_id": run_id,
                })
            row_count = w.row_count

        manifest.record_output(
            "clean", "clean_masters", path=out, row_count=row_count,
        )
        if n_invalid_years > 0:
            manifest.warn(
                "normalize_masters.invalid_years",
                f"{n_invalid_years} master(s) had unparseable year_raw; precision='invalid'",
            )
