"""Step 11 — Finalize manifest: set finished_at and reconcile status."""
from __future__ import annotations

from datetime import datetime, timezone

from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class FinalizeManifestStep:
    name = "finalize_manifest"

    def outputs_exist(self, ctx: RunContext) -> bool:
        return False

    def delete_outputs(self, ctx: RunContext) -> None:
        pass

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest.finalize(finished_at)
        # quality_checks step is what authoritatively sets the status. If for
        # some reason it never ran (only possible via /step invocation), leave
        # the prior value alone.
        ctx.logger.info(
            "finalize_manifest: status=%s finished_at=%s",
            manifest.quality_status,
            finished_at,
        )
