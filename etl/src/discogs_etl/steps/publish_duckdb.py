"""Step 9 — Publish DuckDB at the canonical path (only on a passing run)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..io.duckdb_publisher import publish
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class PublishDuckdbStep:
    name = "publish_duckdb"

    def outputs_exist(self, ctx: RunContext) -> bool:
        # The canonical published path is shared across runs. We always rebuild
        # on the latest passing run rather than skipping based on existence.
        return False

    def delete_outputs(self, ctx: RunContext) -> None:
        # Don't delete the canonical publish on --force; the publish step
        # itself uses atomic-rename, so a successful re-run replaces it.
        pass

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        canonical = ctx.config.paths.published_duckdb
        publish(analytics_dir=ctx.analytics_dir, published_duckdb=canonical)
        manifest.record_output(
            "published",
            "duckdb",
            path=canonical,
            published_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            tables=["release_fact", "release_artist_bridge", "release_label_bridge"],
            views=["release_unique_view"],
        )
        ctx.logger.info("publish_duckdb: published at %s", canonical)
