"""Step (Fase 4) — Build master_fact analytics table.

Per spec ``003-masters-artists`` FR-009 and ``research.md`` R-04 (with
the two-LEFT-JOIN refinement captured in tasks.md T020): build one row
per master_id in the union ``clean_masters ∪ clean_releases.master_id
WHERE NOT NULL``. release_count / earliest_year / latest_year come from
a LEFT JOIN aggregate against ``clean_releases``. ``primary_genre``
comes from ``release_fact`` at any row for the ``main_release_id``
(release-grain via ANY_VALUE; release_fact is row-multiplied by style
but ``primary_genre`` is identical across those rows). ``primary_style``
comes from ``release_fact`` at the row whose
``style_order = 1`` for ``main_release_id`` — when the main_release
has zero styles (style_order = 0 only), no row matches and
``primary_style`` is NULL.

Conditional: skips when ``clean_masters.parquet`` is absent (cascade
from upstream skipping when masters input was missing).
Step ordering: this step MUST run AFTER ``build_release_fact`` so it
can read ``release_fact.parquet`` for the genre / style lookups
(enforced by the runner's STEPS list in ``cli.py``).
"""
from __future__ import annotations

import duckdb

from ..io import schemas
from ..io.parquet_writer import BatchedParquetWriter
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class BuildMasterFactStep:
    name = "build_master_fact"

    def _output(self, ctx: RunContext):
        return ctx.analytics_dir / "master_fact.parquet"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return self._output(ctx).exists()

    def delete_outputs(self, ctx: RunContext) -> None:
        p = self._output(ctx)
        if p.exists():
            p.unlink()

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        log = ctx.logger
        clean_masters = ctx.clean_dir / "clean_masters.parquet"
        if not clean_masters.exists():
            log.info(
                "build_master_fact: %s absent (masters pipeline skipped); skipping",
                clean_masters,
            )
            return

        ctx.analytics_dir.mkdir(parents=True, exist_ok=True)
        out = self._output(ctx)
        run_id = ctx.run_id
        batch_size = ctx.config.limits.parser_batch_size

        clean_releases = ctx.clean_dir / "clean_releases.parquet"
        release_fact = ctx.analytics_dir / "release_fact.parquet"

        sql = f"""
        WITH master_universe AS (
            SELECT DISTINCT master_id FROM read_parquet('{clean_masters.as_posix()}')
            UNION
            SELECT DISTINCT master_id FROM read_parquet('{clean_releases.as_posix()}')
            WHERE master_id IS NOT NULL
        ),
        master_meta AS (
            SELECT master_id, title, main_release_id, year, decade
            FROM read_parquet('{clean_masters.as_posix()}')
        ),
        release_agg AS (
            SELECT master_id,
                   COUNT(*)::INTEGER AS release_count,
                   MIN(year)::INTEGER AS earliest_year,
                   MAX(year)::INTEGER AS latest_year
            FROM read_parquet('{clean_releases.as_posix()}')
            WHERE master_id IS NOT NULL
            GROUP BY 1
        ),
        primary_genre_per_release AS (
            -- release_fact is row-multiplied by style; primary_genre is
            -- release-grain (identical across those rows). ANY_VALUE
            -- collapses to one row per release_id.
            SELECT release_id, ANY_VALUE(primary_genre) AS primary_genre
            FROM read_parquet('{release_fact.as_posix()}')
            GROUP BY release_id
        ),
        primary_style_per_release AS (
            -- The primary style row is the one at style_order = 1.
            -- A release with zero styles has only style_order = 0 in
            -- release_fact, so this CTE has no row → primary_style NULL
            -- after the LEFT JOIN below.
            SELECT release_id, style AS primary_style
            FROM read_parquet('{release_fact.as_posix()}')
            WHERE style_order = 1
        )
        SELECT
            u.master_id,
            m.title,
            m.main_release_id,
            m.year,
            m.decade,
            COALESCE(a.release_count, 0)::INTEGER AS release_count,
            a.earliest_year,
            a.latest_year,
            g.primary_genre,
            s.primary_style
        FROM master_universe u
        LEFT JOIN master_meta             m USING (master_id)
        LEFT JOIN release_agg             a USING (master_id)
        LEFT JOIN primary_genre_per_release g ON g.release_id = m.main_release_id
        LEFT JOIN primary_style_per_release s ON s.release_id = m.main_release_id
        ORDER BY u.master_id
        """

        con = duckdb.connect(":memory:")
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            con.close()

        n_unknown_master_ids = 0
        n_main_release_unresolved = 0
        master_ids_in_meta: set[int] = set()
        with BatchedParquetWriter(out, schemas.MASTER_FACT, batch_size=batch_size) as w:
            for row in rows:
                d = dict(zip(cols, row))
                # An "unknown master_id" is a row with no metadata (came in
                # via clean_releases.master_id but isn't in clean_masters).
                if d["title"] is None and d["main_release_id"] is None and d["year"] is None:
                    n_unknown_master_ids += 1
                else:
                    master_ids_in_meta.add(d["master_id"])
                    # If the master HAS metadata but main_release_id didn't
                    # resolve, count it.
                    if d["main_release_id"] is not None and d["primary_genre"] is None and d["primary_style"] is None:
                        n_main_release_unresolved += 1
                w.write({
                    "master_id": d["master_id"],
                    "title": d["title"],
                    "main_release_id": d["main_release_id"],
                    "year": d["year"],
                    "decade": d["decade"],
                    "release_count": d["release_count"],
                    "earliest_year": d["earliest_year"],
                    "latest_year": d["latest_year"],
                    "primary_genre": d["primary_genre"],
                    "primary_style": d["primary_style"],
                    "run_id": run_id,
                })
            row_count = w.row_count

        manifest.record_output(
            "analytics", "master_fact",
            path=out,
            row_count=row_count,
            distinct_master_count=row_count,
        )

        if n_unknown_master_ids > 0:
            manifest.warn(
                "build_master_fact.unknown_master_ids",
                f"{n_unknown_master_ids} master_id(s) referenced by clean_releases "
                f"are absent from clean_masters",
            )
        if n_main_release_unresolved > 0:
            manifest.warn(
                "build_master_fact.main_release_unresolved",
                f"{n_main_release_unresolved} master(s) had main_release_id "
                f"that didn't resolve to a release_fact row",
            )

        log.info(
            "build_master_fact done: rows=%d unknown_ids=%d unresolved_main=%d",
            row_count, n_unknown_master_ids, n_main_release_unresolved,
        )
