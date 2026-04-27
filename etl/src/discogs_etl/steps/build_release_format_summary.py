"""Step 7 — Build release_format_summary (release-grain format aggregation)."""
from __future__ import annotations

import duckdb

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class BuildReleaseFormatSummaryStep:
    name = "build_release_format_summary"

    def _output(self, ctx: RunContext):
        return ctx.clean_dir / "release_format_summary.parquet"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return self._output(ctx).exists()

    def delete_outputs(self, ctx: RunContext) -> None:
        p = self._output(ctx)
        if p.exists():
            p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        ctx.clean_dir.mkdir(parents=True, exist_ok=True)
        out = self._output(ctx)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size

        clean_releases = (ctx.clean_dir / "clean_releases.parquet").as_posix()
        clean_formats = (ctx.clean_dir / "clean_release_formats.parquet").as_posix()

        # LEFT JOIN so releases with zero formats still emit a summary row.
        sql = f"""
        WITH releases AS (
            SELECT release_id FROM read_parquet('{clean_releases}')
        ),
        formats AS (
            SELECT * FROM read_parquet('{clean_formats}')
        ),
        primary_format AS (
            SELECT
                release_id,
                format_name_raw   AS primary_format_raw,
                format_group      AS primary_format_group,
                format_quantity   AS format_quantity,
                format_description_summary
            FROM formats
            WHERE is_primary_format
        ),
        agg AS (
            SELECT
                release_id,
                COUNT(*)::INTEGER AS format_count,
                BOOL_OR(is_vinyl_format)    AS has_vinyl,
                BOOL_OR(is_cd_format)       AS has_cd,
                BOOL_OR(is_cassette_format) AS has_cassette,
                BOOL_OR(is_digital_format)  AS has_digital,
                BOOL_OR(is_box_set_format)  AS has_box_set
            FROM formats
            GROUP BY 1
        )
        SELECT
            r.release_id,
            pf.primary_format_raw,
            COALESCE(pf.primary_format_group, 'Unknown') AS primary_format_group,
            pf.format_quantity,
            pf.format_description_summary,
            COALESCE(agg.format_count, 0)::INTEGER AS format_count,
            COALESCE(agg.has_vinyl, FALSE)    AS has_vinyl,
            COALESCE(agg.has_cd, FALSE)       AS has_cd,
            COALESCE(agg.has_cassette, FALSE) AS has_cassette,
            COALESCE(agg.has_digital, FALSE)  AS has_digital,
            COALESCE(agg.has_box_set, FALSE)  AS has_box_set
        FROM releases r
        LEFT JOIN primary_format pf USING (release_id)
        LEFT JOIN agg USING (release_id)
        ORDER BY r.release_id
        """
        con = duckdb.connect(":memory:")
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            con.close()

        with BatchedParquetWriter(out, schemas.RELEASE_FORMAT_SUMMARY, batch_size=batch_size) as w:
            for row in rows:
                d = dict(zip(cols, row))
                d["run_id"] = run_id
                # DuckDB returns ints for format_quantity already; ensure int32 fits.
                w.write({
                    "release_id": d["release_id"],
                    "primary_format_raw": d["primary_format_raw"],
                    "primary_format_group": d["primary_format_group"],
                    "format_quantity": d["format_quantity"],
                    "format_description_summary": d["format_description_summary"],
                    "format_count": d["format_count"],
                    "has_vinyl": bool(d["has_vinyl"]),
                    "has_cd": bool(d["has_cd"]),
                    "has_cassette": bool(d["has_cassette"]),
                    "has_digital": bool(d["has_digital"]),
                    "has_box_set": bool(d["has_box_set"]),
                    "run_id": run_id,
                })
            row_count = w.row_count

        manifest.record_output("clean", "release_format_summary", path=out, row_count=row_count)
