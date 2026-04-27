"""Step 8 — Build release_fact + release_artist_bridge + release_label_bridge."""
from __future__ import annotations

import duckdb
import pyarrow.parquet as pq

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


_OUTPUTS = ("release_fact", "release_artist_bridge", "release_label_bridge")


class BuildReleaseFactStep:
    name = "build_release_fact"

    def _outputs(self, ctx: RunContext):
        return {n: ctx.analytics_dir / f"{n}.parquet" for n in _OUTPUTS}

    def outputs_exist(self, ctx: RunContext) -> bool:
        return all(p.exists() for p in self._outputs(ctx).values())

    def delete_outputs(self, ctx: RunContext) -> None:
        for p in self._outputs(ctx).values():
            if p.exists():
                p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        ctx.analytics_dir.mkdir(parents=True, exist_ok=True)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size
        paths = self._outputs(ctx)

        clean_releases = (ctx.clean_dir / "clean_releases.parquet").as_posix()
        clean_artists = (ctx.clean_dir / "clean_release_artists.parquet").as_posix()
        clean_labels = (ctx.clean_dir / "clean_release_labels.parquet").as_posix()
        clean_genres = (ctx.clean_dir / "clean_release_genres.parquet").as_posix()
        clean_styles = (ctx.clean_dir / "clean_release_styles.parquet").as_posix()
        rfs = (ctx.clean_dir / "release_format_summary.parquet").as_posix()

        # --- release_fact: clean_releases + primary artist/label/genre + summary + LEFT JOIN styles
        # Releases with zero styles emit one row with style_order=0, style=NULL.
        rf_sql = f"""
        WITH releases AS (
            SELECT * FROM read_parquet('{clean_releases}')
        ),
        primary_artist AS (
            SELECT release_id, artist_id AS primary_artist_id, artist_name AS primary_artist_name
            FROM read_parquet('{clean_artists}')
            WHERE is_primary_artist
        ),
        primary_label AS (
            SELECT release_id, label_id AS primary_label_id, label_name AS primary_label_name
            FROM read_parquet('{clean_labels}')
            WHERE is_primary_label
        ),
        primary_genre AS (
            SELECT release_id, genre AS primary_genre
            FROM read_parquet('{clean_genres}')
            WHERE is_primary_genre
        ),
        summary AS (
            SELECT * FROM read_parquet('{rfs}')
        ),
        styles AS (
            SELECT release_id, style_order, style FROM read_parquet('{clean_styles}')
        )
        SELECT
            r.release_id,
            r.master_id,
            r.title,
            pa.primary_artist_id,
            pa.primary_artist_name,
            r.country,
            r.released_raw,
            r.year,
            r.month,
            r.day,
            r.released_date,
            r.released_date_precision,
            r.decade,
            r.data_quality,
            r.track_count,
            r.artist_count,
            r.label_count,
            r.genre_count,
            r.style_count,
            r.format_count,
            pl.primary_label_id,
            pl.primary_label_name,
            s.primary_format_raw,
            s.primary_format_group,
            s.format_quantity,
            s.format_description_summary,
            s.has_vinyl,
            s.has_cd,
            s.has_cassette,
            s.has_digital,
            s.has_box_set,
            pg.primary_genre,
            sty.style,
            COALESCE(sty.style_order, 0)::INTEGER AS style_order
        FROM releases r
        LEFT JOIN primary_artist pa USING (release_id)
        LEFT JOIN primary_label  pl USING (release_id)
        LEFT JOIN primary_genre  pg USING (release_id)
        LEFT JOIN summary        s  USING (release_id)
        LEFT JOIN styles         sty USING (release_id)
        ORDER BY r.release_id, COALESCE(sty.style_order, 0)
        """
        con = duckdb.connect(":memory:")
        try:
            cur = con.execute(rf_sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            con.close()

        distinct_release_ids: set[int] = set()
        with BatchedParquetWriter(paths["release_fact"], schemas.RELEASE_FACT, batch_size=batch_size) as w:
            for row in rows:
                d = dict(zip(cols, row))
                distinct_release_ids.add(d["release_id"])
                w.write({
                    "release_id": d["release_id"],
                    "master_id": d["master_id"],
                    "title": d["title"],
                    "primary_artist_id": d["primary_artist_id"],
                    "primary_artist_name": d["primary_artist_name"],
                    "country": d["country"],
                    "released_raw": d["released_raw"],
                    "year": d["year"],
                    "month": d["month"],
                    "day": d["day"],
                    "released_date": d["released_date"],
                    "released_date_precision": d["released_date_precision"],
                    "decade": d["decade"],
                    "data_quality": d["data_quality"],
                    "track_count": d["track_count"],
                    "artist_count": d["artist_count"],
                    "label_count": d["label_count"],
                    "genre_count": d["genre_count"],
                    "style_count": d["style_count"],
                    "format_count": d["format_count"],
                    "primary_label_id": d["primary_label_id"],
                    "primary_label_name": d["primary_label_name"],
                    "primary_format_raw": d["primary_format_raw"],
                    "primary_format_group": d["primary_format_group"] or "Unknown",
                    "format_quantity": d["format_quantity"],
                    "format_description_summary": d["format_description_summary"],
                    "has_vinyl": bool(d["has_vinyl"]) if d["has_vinyl"] is not None else False,
                    "has_cd": bool(d["has_cd"]) if d["has_cd"] is not None else False,
                    "has_cassette": bool(d["has_cassette"]) if d["has_cassette"] is not None else False,
                    "has_digital": bool(d["has_digital"]) if d["has_digital"] is not None else False,
                    "has_box_set": bool(d["has_box_set"]) if d["has_box_set"] is not None else False,
                    "primary_genre": d["primary_genre"],
                    "style": d["style"],
                    "style_order": d["style_order"],
                    "run_id": run_id,
                })
            rf_row_count = w.row_count

        manifest.record_output(
            "analytics", "release_fact",
            path=paths["release_fact"],
            row_count=rf_row_count,
            distinct_release_count=len(distinct_release_ids),
        )

        # --- release_artist_bridge: passthrough of clean_release_artists in §9.2 column order
        artists = pq.read_table(clean_artists)
        with BatchedParquetWriter(paths["release_artist_bridge"], schemas.RELEASE_ARTIST_BRIDGE, batch_size=batch_size) as w:
            for r in artists.to_pylist():
                w.write({
                    "release_id": r["release_id"],
                    "artist_id": r["artist_id"],
                    "artist_name": r["artist_name"],
                    "artist_order": r["artist_order"],
                    "artist_anv": r["artist_anv"],
                    "artist_join": r["artist_join"],
                    "is_primary_artist": bool(r["is_primary_artist"]),
                    "run_id": run_id,
                })
            rab_count = w.row_count
        manifest.record_output("analytics", "release_artist_bridge",
                               path=paths["release_artist_bridge"], row_count=rab_count)

        # --- release_label_bridge: passthrough of clean_release_labels in §9.3 column order
        labels = pq.read_table(clean_labels)
        with BatchedParquetWriter(paths["release_label_bridge"], schemas.RELEASE_LABEL_BRIDGE, batch_size=batch_size) as w:
            for r in labels.to_pylist():
                w.write({
                    "release_id": r["release_id"],
                    "label_id": r["label_id"],
                    "label_name": r["label_name"],
                    "label_order": r["label_order"],
                    "catno": r["catno"],
                    "is_primary_label": bool(r["is_primary_label"]),
                    "run_id": run_id,
                })
            rlb_count = w.row_count
        manifest.record_output("analytics", "release_label_bridge",
                               path=paths["release_label_bridge"], row_count=rlb_count)
