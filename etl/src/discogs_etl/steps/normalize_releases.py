"""Step 5 — Normalize releases (dates, decade, per-release counts)."""
from __future__ import annotations

import duckdb

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..transforms.date_normalization import parse_released


class NormalizeReleasesStep:
    name = "normalize_releases"

    def _output(self, ctx: RunContext):
        return ctx.clean_dir / "clean_releases.parquet"

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
        s = ctx.staging_dir

        sql = f"""
        SELECT
            r.release_id,
            r.title,
            r.country,
            r.released_raw,
            r.data_quality,
            r.master_id,
            r.master_is_main_release,
            r.has_videos,
            r.has_extraartists,
            COALESCE(track_counts.c, 0)::INTEGER AS track_count,
            COALESCE(artist_counts.c, 0)::INTEGER AS artist_count,
            COALESCE(label_counts.c, 0)::INTEGER AS label_count,
            COALESCE(genre_counts.c, 0)::INTEGER AS genre_count,
            COALESCE(style_counts.c, 0)::INTEGER AS style_count,
            COALESCE(format_counts.c, 0)::INTEGER AS format_count
        FROM read_parquet('{(s / "stg_releases.parquet").as_posix()}') r
        LEFT JOIN (SELECT release_id, COUNT(*) AS c FROM read_parquet('{(s / "stg_release_tracks.parquet").as_posix()}') GROUP BY 1) track_counts USING (release_id)
        LEFT JOIN (SELECT release_id, COUNT(*) AS c FROM read_parquet('{(s / "stg_release_artists.parquet").as_posix()}') GROUP BY 1) artist_counts USING (release_id)
        LEFT JOIN (SELECT release_id, COUNT(*) AS c FROM read_parquet('{(s / "stg_release_labels.parquet").as_posix()}') GROUP BY 1) label_counts USING (release_id)
        LEFT JOIN (SELECT release_id, COUNT(*) AS c FROM read_parquet('{(s / "stg_release_genres.parquet").as_posix()}') GROUP BY 1) genre_counts USING (release_id)
        LEFT JOIN (SELECT release_id, COUNT(*) AS c FROM read_parquet('{(s / "stg_release_styles.parquet").as_posix()}') GROUP BY 1) style_counts USING (release_id)
        LEFT JOIN (SELECT release_id, COUNT(*) AS c FROM read_parquet('{(s / "stg_release_formats.parquet").as_posix()}') GROUP BY 1) format_counts USING (release_id)
        ORDER BY r.release_id
        """
        con = duckdb.connect(":memory:")
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            con.close()

        n_invalid_dates = 0
        with BatchedParquetWriter(out, schemas.CLEAN_RELEASES, batch_size=batch_size) as w:
            for row in rows:
                d = dict(zip(cols, row))
                pd = parse_released(d["released_raw"])
                if pd.released_date_precision == "invalid":
                    n_invalid_dates += 1
                w.write({
                    "release_id": d["release_id"],
                    "title": d["title"],
                    "country": d["country"],
                    "released_raw": d["released_raw"],
                    "year": pd.year,
                    "month": pd.month,
                    "day": pd.day,
                    "released_date": pd.released_date,
                    "released_date_precision": pd.released_date_precision,
                    "decade": pd.decade,
                    "data_quality": d["data_quality"],
                    "master_id": d["master_id"],
                    "master_is_main_release": d["master_is_main_release"],
                    "track_count": d["track_count"],
                    "artist_count": d["artist_count"],
                    "label_count": d["label_count"],
                    "genre_count": d["genre_count"],
                    "style_count": d["style_count"],
                    "format_count": d["format_count"],
                    "has_videos": bool(d["has_videos"]),
                    "has_extraartists": bool(d["has_extraartists"]),
                    "run_id": run_id,
                })
            row_count = w.row_count

        manifest.record_output("clean", "clean_releases", path=out, row_count=row_count)
        if n_invalid_dates > 0:
            manifest.warn(
                "normalize_releases.invalid_dates",
                f"{n_invalid_dates} release(s) had unparseable released dates; precision='invalid'",
            )
