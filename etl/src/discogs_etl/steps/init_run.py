"""Step 0 — Init run: ensure per-run output directories exist."""
from __future__ import annotations

from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class InitRunStep:
    name = "init_run"

    def outputs_exist(self, ctx: RunContext) -> bool:
        # Idempotent — always run; mkdir(exist_ok=True) is cheap.
        return False

    def delete_outputs(self, ctx: RunContext) -> None:
        # Don't remove run dirs on --force; that's the caller's call.
        pass

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        for d in (
            ctx.staging_dir,
            ctx.clean_dir,
            ctx.analytics_dir,
            ctx.config.paths.published_duckdb.parent,
            ctx.config.paths.manifests_dir,
            ctx.config.paths.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
