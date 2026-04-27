"""Generic step orchestrator with --skip-existing / --force semantics.

A step is any object satisfying the Step protocol below. Steps are sequenced
by the runner; per-step duration is recorded in the manifest. On a critical
DQ failure (signalled by the quality_checks step setting
``manifest.quality_status == "failed"``), the runner skips the publish step
per FR-022 but still runs the finalize_manifest step.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from .context import RunContext
from .manifest import Manifest, QualityStatus


@runtime_checkable
class Step(Protocol):
    name: str

    def outputs_exist(self, ctx: RunContext) -> bool: ...
    def delete_outputs(self, ctx: RunContext) -> None: ...
    def run(self, ctx: RunContext, manifest: Manifest) -> None: ...


@dataclass
class RunResult:
    final_status: QualityStatus
    exit_code: int


PUBLISH_STEP_NAME = "publish_duckdb"
QUALITY_STEP_NAME = "quality_checks"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pipeline(
    ctx: RunContext,
    steps: list[Step],
    manifest: Manifest,
    *,
    skip_existing: bool = False,
    force: bool = False,
) -> RunResult:
    """Execute steps in order; record durations and outputs into the manifest.

    Returns a RunResult with the final quality status and exit code.
    """
    log = ctx.logger
    quality_failed = False

    for step in steps:
        # FR-022: skip publish on a failed run.
        if step.name == PUBLISH_STEP_NAME and quality_failed:
            log.warning(
                "Skipping step '%s' because quality_checks reported failed", step.name
            )
            continue

        if force:
            try:
                step.delete_outputs(ctx)
            except Exception as e:  # noqa: BLE001 — log and continue
                log.warning("delete_outputs(%s) raised %s; continuing", step.name, e)

        if skip_existing and step.outputs_exist(ctx):
            log.info("Step %s: outputs already exist; skipping", step.name)
            if step.name not in manifest.data.get("step_durations", {}):
                manifest.record_step_duration(step.name, 0.0)
                manifest.save()
            continue

        log.info("Step %s: starting", step.name)
        t0 = time.monotonic()
        try:
            step.run(ctx, manifest)
        except Exception:
            log.exception("Step %s: failed with uncaught exception", step.name)
            manifest.record_step_duration(step.name, time.monotonic() - t0)
            manifest.set_quality_status("incomplete")
            manifest.finalize(_utc_now_iso())
            manifest.save()
            return RunResult(final_status="incomplete", exit_code=1)
        dt = time.monotonic() - t0
        manifest.record_step_duration(step.name, dt)
        manifest.save()
        log.info("Step %s: done in %.2fs", step.name, dt)

        if step.name == QUALITY_STEP_NAME and manifest.quality_status == "failed":
            log.error(
                "Critical DQ failure — publish step will be skipped per FR-022"
            )
            quality_failed = True

    final_status = manifest.quality_status
    exit_code = 0 if final_status in ("passed", "passed_with_warnings") else 1
    return RunResult(final_status=final_status, exit_code=exit_code)
