"""Step 2 — Parse releases.xml in streaming mode and write staging Parquet."""
from __future__ import annotations

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..parsers.releases_parser import iter_releases
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..transforms.text_normalization import clean_bool_attr, clean_int


_OUTPUT_NAMES = (
    "stg_releases",
    "stg_release_artists",
    "stg_release_labels",
    "stg_release_formats",
    "stg_release_format_descriptions",
    "stg_release_genres",
    "stg_release_styles",
    "stg_release_tracks",
)


class ParseReleasesStep:
    name = "parse_releases"

    def __init__(self, *, limit_releases: int | None = None) -> None:
        self.limit_releases = limit_releases

    def _outputs(self, ctx: RunContext) -> dict[str, "object"]:
        return {n: ctx.staging_dir / f"{n}.parquet" for n in _OUTPUT_NAMES}

    def outputs_exist(self, ctx: RunContext) -> bool:
        return all(p.exists() for p in self._outputs(ctx).values())

    def delete_outputs(self, ctx: RunContext) -> None:
        for p in self._outputs(ctx).values():
            if p.exists():
                p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        log = ctx.logger
        ctx.staging_dir.mkdir(parents=True, exist_ok=True)
        source_path = ctx.releases_xml_path()
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size
        progress_every = max(1, ctx.config.limits.log_progress_every)
        paths = self._outputs(ctx)

        n_in = 0
        n_emitted = 0
        n_dropped = 0

        with BatchedParquetWriter(paths["stg_releases"], schemas.STG_RELEASES, batch_size=batch_size) as w_rel, \
             BatchedParquetWriter(paths["stg_release_artists"], schemas.STG_RELEASE_ARTISTS, batch_size=batch_size) as w_art, \
             BatchedParquetWriter(paths["stg_release_labels"], schemas.STG_RELEASE_LABELS, batch_size=batch_size) as w_lab, \
             BatchedParquetWriter(paths["stg_release_formats"], schemas.STG_RELEASE_FORMATS, batch_size=batch_size) as w_fmt, \
             BatchedParquetWriter(paths["stg_release_format_descriptions"], schemas.STG_RELEASE_FORMAT_DESCRIPTIONS, batch_size=batch_size) as w_fd, \
             BatchedParquetWriter(paths["stg_release_genres"], schemas.STG_RELEASE_GENRES, batch_size=batch_size) as w_gen, \
             BatchedParquetWriter(paths["stg_release_styles"], schemas.STG_RELEASE_STYLES, batch_size=batch_size) as w_sty, \
             BatchedParquetWriter(paths["stg_release_tracks"], schemas.STG_RELEASE_TRACKS, batch_size=batch_size) as w_trk:

            for record in iter_releases(source_path, limit=self.limit_releases):
                n_in += 1
                rel = record["release"]
                rid = clean_int(rel["release_id_raw"])
                if rid is None:
                    n_dropped += 1
                    continue

                w_rel.write({
                    "release_id": rid,
                    "title": rel["title"],
                    "country": rel["country"],
                    "released_raw": rel["released_raw"],
                    "notes": rel["notes"],
                    "data_quality": rel["data_quality"],
                    "master_id": clean_int(rel["master_id_raw"]),
                    "master_is_main_release": clean_bool_attr(rel["master_is_main_release_raw"]),
                    "status": rel["status"],
                    "has_videos": bool(rel["has_videos"]),
                    "has_extraartists": bool(rel["has_extraartists"]),
                    "source_file": str(source_path),
                    "parsed_at": rel["parsed_at"],
                    "run_id": run_id,
                })

                for a in record["artists"]:
                    w_art.write({
                        "release_id": rid,
                        "artist_order": a["artist_order"],
                        "artist_id": clean_int(a["artist_id_raw"]),
                        "artist_name": a["artist_name"],
                        "artist_anv": a["artist_anv"],
                        "artist_join": a["artist_join"],
                        "run_id": run_id,
                    })

                for l in record["labels"]:
                    w_lab.write({
                        "release_id": rid,
                        "label_order": l["label_order"],
                        "label_id": clean_int(l["label_id_raw"]),
                        "label_name": l["label_name"],
                        "catno": l["catno"],
                        "run_id": run_id,
                    })

                for f in record["formats"]:
                    w_fmt.write({
                        "release_id": rid,
                        "format_order": f["format_order"],
                        "format_name": f["format_name"],
                        "format_qty_raw": f["format_qty_raw"],
                        "format_text": f["format_text"],
                        "run_id": run_id,
                    })

                for fd in record["format_descriptions"]:
                    w_fd.write({
                        "release_id": rid,
                        "format_order": fd["format_order"],
                        "description_order": fd["description_order"],
                        "description": fd["description"],
                        "run_id": run_id,
                    })

                for g in record["genres"]:
                    w_gen.write({
                        "release_id": rid,
                        "genre_order": g["genre_order"],
                        "genre": g["genre"],
                        "run_id": run_id,
                    })

                for s in record["styles"]:
                    w_sty.write({
                        "release_id": rid,
                        "style_order": s["style_order"],
                        "style": s["style"],
                        "run_id": run_id,
                    })

                for t in record["tracks"]:
                    w_trk.write({
                        "release_id": rid,
                        "track_order": t["track_order"],
                        "position": t["position"],
                        "title": t["title"],
                        "duration_raw": t["duration_raw"],
                        "track_type": t["track_type"],
                        "run_id": run_id,
                    })

                n_emitted += 1
                if n_emitted % progress_every == 0:
                    log.info("parse_releases: %d releases emitted", n_emitted)

            row_counts = {
                "stg_releases": w_rel.row_count,
                "stg_release_artists": w_art.row_count,
                "stg_release_labels": w_lab.row_count,
                "stg_release_formats": w_fmt.row_count,
                "stg_release_format_descriptions": w_fd.row_count,
                "stg_release_genres": w_gen.row_count,
                "stg_release_styles": w_sty.row_count,
                "stg_release_tracks": w_trk.row_count,
            }

        for name, count in row_counts.items():
            manifest.record_output("staging", name, path=paths[name], row_count=count)

        if n_dropped > 0:
            manifest.warn(
                "parse_releases.dropped_no_release_id",
                f"{n_dropped} of {n_in} <release> elements had no parseable id; dropped",
            )

        log.info(
            "parse_releases done: in=%d emitted=%d dropped=%d", n_in, n_emitted, n_dropped
        )
