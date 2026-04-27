"""Step 10 — Run data quality checks across staging, clean, and analytics layers."""
from __future__ import annotations

import pyarrow.parquet as pq

from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest
from ..quality.checks import (
    run_analytics_checks,
    run_clean_checks,
    run_staging_checks,
)
from ..quality.report import derive_status


class QualityChecksStep:
    name = "quality_checks"

    def outputs_exist(self, ctx: RunContext) -> bool:
        # Pure manifest mutation; always re-run on --skip-existing.
        return False

    def delete_outputs(self, ctx: RunContext) -> None:
        pass

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        log = ctx.logger
        all_results = []

        all_results.extend(run_staging_checks(ctx.staging_dir))
        all_results.extend(run_clean_checks(ctx.clean_dir))

        clean_releases_count = int(
            pq.read_metadata(ctx.clean_dir / "clean_releases.parquet").num_rows
        )
        all_results.extend(run_analytics_checks(ctx.analytics_dir, clean_releases_count))

        for r in all_results:
            manifest.record_check_result(r)

        status = derive_status(all_results)
        manifest.set_quality_status(status)

        n_total = len(all_results)
        n_failed = sum(1 for r in all_results if not r.passed)
        log.info(
            "quality_checks: status=%s checks=%d failed=%d", status, n_total, n_failed
        )
