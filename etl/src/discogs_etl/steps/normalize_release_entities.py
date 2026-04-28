"""Step 6 — Normalize release entities (artists, labels, formats, genres, styles)."""
from __future__ import annotations

from collections import defaultdict

import pyarrow.parquet as pq

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..pipeline.progress import ProgressReporter
from ..transforms.format_normalization import (
    derive_format_group,
    derive_is_box_set,
    derive_is_cassette,
    derive_is_cd,
    derive_is_digital,
    derive_is_vinyl,
    description_summary,
)
from ..transforms.text_normalization import clean_int, clean_text


_OUTPUTS = (
    "clean_release_artists",
    "clean_release_labels",
    "clean_release_formats",
    "clean_release_genres",
    "clean_release_styles",
)


class NormalizeReleaseEntitiesStep:
    name = "normalize_release_entities"

    def _outputs(self, ctx: RunContext):
        return {n: ctx.clean_dir / f"{n}.parquet" for n in _OUTPUTS}

    def outputs_exist(self, ctx: RunContext) -> bool:
        return all(p.exists() for p in self._outputs(ctx).values())

    def delete_outputs(self, ctx: RunContext) -> None:
        for p in self._outputs(ctx).values():
            if p.exists():
                p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        ctx.clean_dir.mkdir(parents=True, exist_ok=True)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size
        paths = self._outputs(ctx)

        self._normalize_simple(
            staging=ctx.staging_dir / "stg_release_artists.parquet",
            output=paths["clean_release_artists"],
            schema=schemas.CLEAN_RELEASE_ARTISTS,
            run_id=run_id, batch_size=batch_size,
            transform=self._artist_row,
        )
        manifest.record_output("clean", "clean_release_artists",
                               path=paths["clean_release_artists"],
                               row_count=_count_rows(paths["clean_release_artists"]))

        self._normalize_labels(
            staging=ctx.staging_dir / "stg_release_labels.parquet",
            output=paths["clean_release_labels"],
            run_id=run_id, batch_size=batch_size,
        )
        manifest.record_output("clean", "clean_release_labels",
                               path=paths["clean_release_labels"],
                               row_count=_count_rows(paths["clean_release_labels"]))

        reporter = ProgressReporter(
            ctx.logger, self.name, ctx.config.limits.log_progress_every,
        )
        n_unmapped, n_qty_overflow = self._normalize_formats(
            ctx=ctx, run_id=run_id, batch_size=batch_size, paths=paths,
            reporter=reporter,
        )
        metrics = reporter.final()
        manifest.record_step_metrics(
            self.name, releases_per_sec=metrics.releases_per_sec,
        )
        manifest.record_output("clean", "clean_release_formats",
                               path=paths["clean_release_formats"],
                               row_count=_count_rows(paths["clean_release_formats"]))
        if n_unmapped > 0:
            manifest.warn(
                "normalize_release_entities.unmapped_format_names",
                f"{n_unmapped} format row(s) had unmapped format_name; mapped to 'Other'",
            )
        if n_qty_overflow > 0:
            manifest.warn(
                "normalize_release_entities.format_quantity_overflow",
                f"{n_qty_overflow} format row(s) had qty values outside int64 range; "
                "stored as NULL (Discogs data artifact)",
            )

        self._normalize_simple(
            staging=ctx.staging_dir / "stg_release_genres.parquet",
            output=paths["clean_release_genres"],
            schema=schemas.CLEAN_RELEASE_GENRES,
            run_id=run_id, batch_size=batch_size,
            transform=self._genre_row,
        )
        manifest.record_output("clean", "clean_release_genres",
                               path=paths["clean_release_genres"],
                               row_count=_count_rows(paths["clean_release_genres"]))

        self._normalize_simple(
            staging=ctx.staging_dir / "stg_release_styles.parquet",
            output=paths["clean_release_styles"],
            schema=schemas.CLEAN_RELEASE_STYLES,
            run_id=run_id, batch_size=batch_size,
            transform=self._style_row,
        )
        manifest.record_output("clean", "clean_release_styles",
                               path=paths["clean_release_styles"],
                               row_count=_count_rows(paths["clean_release_styles"]))

    # ----- helpers -----

    @staticmethod
    def _artist_row(row, run_id):
        return {
            "release_id": row["release_id"],
            "artist_order": row["artist_order"],
            "artist_id": row["artist_id"],
            "artist_name": clean_text(row["artist_name"]),
            "artist_anv": clean_text(row["artist_anv"]),
            "artist_join": clean_text(row["artist_join"]),
            "is_primary_artist": int(row["artist_order"]) == 1,
            "run_id": run_id,
        }

    @staticmethod
    def _genre_row(row, run_id):
        return {
            "release_id": row["release_id"],
            "genre_order": row["genre_order"],
            "genre": clean_text(row["genre"]),
            "is_primary_genre": int(row["genre_order"]) == 1,
            "run_id": run_id,
        }

    @staticmethod
    def _style_row(row, run_id):
        return {
            "release_id": row["release_id"],
            "style_order": row["style_order"],
            "style": clean_text(row["style"]),
            "run_id": run_id,
        }

    @staticmethod
    def _normalize_simple(*, staging, output, schema, run_id, batch_size, transform):
        table = pq.read_table(staging)
        with BatchedParquetWriter(output, schema, batch_size=batch_size) as w:
            for row in table.to_pylist():
                w.write(transform(row, run_id))

    @staticmethod
    def _normalize_labels(*, staging, output, run_id, batch_size):
        """Apply the §7.3 dedup rule: drop exact (release_id, label_id, label_name, catno)
        duplicates; keep entries differing in catno."""
        table = pq.read_table(staging)
        seen: set[tuple] = set()
        with BatchedParquetWriter(output, schemas.CLEAN_RELEASE_LABELS, batch_size=batch_size) as w:
            for row in table.to_pylist():
                rid = row["release_id"]
                lid = row["label_id"]
                name = clean_text(row["label_name"])
                catno = clean_text(row["catno"])
                key = (rid, lid, name, catno)
                if key in seen:
                    continue
                seen.add(key)
                w.write({
                    "release_id": rid,
                    "label_order": row["label_order"],
                    "label_id": lid,
                    "label_name": name,
                    "catno": catno,
                    "is_primary_label": int(row["label_order"]) == 1,
                    "run_id": run_id,
                })

    @staticmethod
    def _normalize_formats(
        *, ctx: RunContext, run_id, batch_size, paths,
        reporter: ProgressReporter | None = None,
    ) -> tuple[int, int]:
        """Join staging format rows with their descriptions and derive flags.

        Returns (n_unmapped_format_names, n_qty_overflow). Real Discogs data
        contains absurd ``qty`` typos (e.g. 60-digit integers) that exceed
        any fixed-width integer type. We NULL such values and count them
        for a manifest warning rather than letting pyarrow blow up the run.
        """
        fmt_path = ctx.staging_dir / "stg_release_formats.parquet"
        desc_path = ctx.staging_dir / "stg_release_format_descriptions.parquet"

        # int64 fits the legitimate-but-large qty values (e.g. 5_000_000_000,
        # 9_999_999_999) seen in the wild. Anything outside this range is
        # treated as data garbage and stored as NULL.
        _INT64_MAX = (1 << 63) - 1
        _INT64_MIN = -(1 << 63)

        descs_by_format: dict[tuple[int, int], list[str]] = defaultdict(list)
        for row in pq.read_table(desc_path).to_pylist():
            d = clean_text(row["description"])
            if d is None:
                continue
            descs_by_format[(row["release_id"], row["format_order"])].append(d)

        n_unmapped = 0
        n_qty_overflow = 0
        with BatchedParquetWriter(paths["clean_release_formats"],
                                  schemas.CLEAN_RELEASE_FORMATS,
                                  batch_size=batch_size) as w:
            for n, row in enumerate(pq.read_table(fmt_path).to_pylist(), start=1):
                if reporter is not None:
                    reporter.report_iteration(n)
                rid = row["release_id"]
                order = int(row["format_order"])
                name_raw = clean_text(row["format_name"])
                qty = clean_int(row["format_qty_raw"])
                if qty is not None and not (_INT64_MIN <= qty <= _INT64_MAX):
                    n_qty_overflow += 1
                    qty = None
                text = clean_text(row["format_text"])
                descs = descs_by_format.get((rid, order), [])
                group, was_mapped = derive_format_group(name_raw)
                if not was_mapped and name_raw:
                    n_unmapped += 1
                w.write({
                    "release_id": rid,
                    "format_order": order,
                    "format_name_raw": name_raw,
                    "format_group": group,
                    "format_quantity": qty,
                    "format_text": text,
                    "format_description_summary": description_summary(descs),
                    "is_primary_format": order == 1,
                    "is_vinyl_format": derive_is_vinyl(group, descs),
                    "is_cd_format": derive_is_cd(group),
                    "is_cassette_format": derive_is_cassette(group),
                    "is_digital_format": derive_is_digital(group),
                    "is_box_set_format": derive_is_box_set(group, descs),
                    "run_id": run_id,
                })
        return n_unmapped, n_qty_overflow


def _count_rows(parquet_path) -> int:
    return int(pq.read_metadata(parquet_path).num_rows)
