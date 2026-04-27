"""CLI for the Discogs ETL — Fase 1.

See specs/001-discogs-etl/contracts/cli.md for the contract.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import click

from . import __version__ as ETL_VERSION
from .io.file_utils import make_run_id
from .pipeline.context import RunConfig, RunContext, configure_logging
from .pipeline.manifest import Manifest
from .pipeline.runner import run_pipeline
from .steps.build_release_fact import BuildReleaseFactStep
from .steps.build_release_format_summary import BuildReleaseFormatSummaryStep
from .steps.finalize_manifest import FinalizeManifestStep
from .steps.init_run import InitRunStep
from .steps.normalize_release_entities import NormalizeReleaseEntitiesStep
from .steps.normalize_releases import NormalizeReleasesStep
from .steps.parse_releases import ParseReleasesStep
from .steps.prepare_sources import PrepareSourcesStep
from .steps.publish_duckdb import PublishDuckdbStep
from .steps.quality_checks import QualityChecksStep


_CLI_TO_INTERNAL = {
    "init-run": "init_run",
    "prepare-sources": "prepare_sources",
    "parse-releases": "parse_releases",
    "normalize-releases": "normalize_releases",
    "normalize-release-entities": "normalize_release_entities",
    "build-release-format-summary": "build_release_format_summary",
    "build-release-fact": "build_release_fact",
    "quality-checks": "quality_checks",
    "publish-duckdb": "publish_duckdb",
    "finalize-manifest": "finalize_manifest",
}


def _build_steps(*, limit_releases: int | None) -> list:
    return [
        InitRunStep(),
        PrepareSourcesStep(),
        ParseReleasesStep(limit_releases=limit_releases),
        NormalizeReleasesStep(),
        NormalizeReleaseEntitiesStep(),
        BuildReleaseFormatSummaryStep(),
        BuildReleaseFactStep(),
        QualityChecksStep(),
        PublishDuckdbStep(),
        FinalizeManifestStep(),
    ]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup(
    *,
    config_path: str,
    run_id: str | None,
    snapshot_id: str | None,
    force: bool,
    skip_existing: bool,
) -> tuple[RunContext, Manifest]:
    cfg = RunConfig.load(config_path)
    if snapshot_id is not None:
        cfg.snapshot_id = snapshot_id
    rid = run_id or make_run_id()
    logger = configure_logging(rid, cfg)
    ctx = RunContext(run_id=rid, snapshot_id=cfg.snapshot_id, config=cfg, logger=logger)
    logger.info("CLI: run_id=%s snapshot_id=%s", rid, cfg.snapshot_id)

    manifest_path = ctx.manifest_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists():
        if force:
            logger.info("Manifest exists at %s; --force: overwriting", manifest_path)
            manifest = Manifest.create(
                manifest_path,
                run_id=rid,
                snapshot_id=cfg.snapshot_id,
                etl_version=ETL_VERSION,
                started_at=_utc_now_iso(),
                config_path=cfg.config_path,
                config_sha256=cfg.config_sha256,
            )
        elif skip_existing:
            logger.info("Manifest exists at %s; --skip-existing: loading", manifest_path)
            manifest = Manifest.load(manifest_path)
        else:
            click.echo(
                f"Error: manifest already exists at {manifest_path}. "
                "Use --force to overwrite or --skip-existing to continue.",
                err=True,
            )
            sys.exit(2)
    else:
        manifest = Manifest.create(
            manifest_path,
            run_id=rid,
            snapshot_id=cfg.snapshot_id,
            etl_version=ETL_VERSION,
            started_at=_utc_now_iso(),
            config_path=cfg.config_path,
            config_sha256=cfg.config_sha256,
        )

    return ctx, manifest


def _common_options(fn):
    fn = click.option(
        "--skip-existing", is_flag=True, default=False,
        help="Skip steps whose declared outputs already exist.",
    )(fn)
    fn = click.option(
        "--force", is_flag=True, default=False,
        help="Allow overwriting outputs at an existing run_id.",
    )(fn)
    fn = click.option(
        "--limit-releases", default=None, type=click.IntRange(min=1),
        help="Stop after N <release> elements (debug / fast iteration).",
    )(fn)
    fn = click.option(
        "--snapshot-id", default=None,
        help="Override snapshot_id from the config.",
    )(fn)
    fn = click.option(
        "--run-id", default=None,
        help="Override the auto-generated run id.",
    )(fn)
    fn = click.option(
        "--config", "config_path", required=True,
        type=click.Path(exists=True, dir_okay=False),
        help="YAML config file (e.g., etl/configs/base.yml).",
    )(fn)
    return fn


@click.group()
@click.version_option(ETL_VERSION, prog_name="discogs-etl")
def cli() -> None:
    """Discogs ETL — Fase 1 sample vertical slice."""


@cli.command("run")
@_common_options
def run_cmd(
    config_path: str,
    run_id: str | None,
    snapshot_id: str | None,
    limit_releases: int | None,
    force: bool,
    skip_existing: bool,
) -> None:
    """Execute the full pipeline end-to-end."""
    ctx, manifest = _setup(
        config_path=config_path,
        run_id=run_id,
        snapshot_id=snapshot_id,
        force=force,
        skip_existing=skip_existing,
    )
    steps = _build_steps(limit_releases=limit_releases)
    result = run_pipeline(ctx, steps, manifest, skip_existing=skip_existing, force=force)
    sys.exit(result.exit_code)


@cli.command("step")
@click.argument("step_name", type=str)
@_common_options
def step_cmd(
    step_name: str,
    config_path: str,
    run_id: str | None,
    snapshot_id: str | None,
    limit_releases: int | None,
    force: bool,
    skip_existing: bool,
) -> None:
    """Execute a single step within an existing (or new) run."""
    internal = _CLI_TO_INTERNAL.get(step_name)
    if internal is None:
        click.echo(
            f"Unknown step '{step_name}'. Allowed: {sorted(_CLI_TO_INTERNAL)}",
            err=True,
        )
        sys.exit(2)

    if internal != "init_run" and run_id is None:
        click.echo(
            f"--run-id is required when running step '{step_name}' "
            "(steps after init_run must reference an existing run).",
            err=True,
        )
        sys.exit(2)

    ctx, manifest = _setup(
        config_path=config_path,
        run_id=run_id,
        snapshot_id=snapshot_id,
        force=force,
        skip_existing=skip_existing,
    )
    steps = _build_steps(limit_releases=limit_releases)
    target = next((s for s in steps if s.name == internal), None)
    assert target is not None
    result = run_pipeline(
        ctx, [target], manifest, skip_existing=skip_existing, force=force
    )
    sys.exit(result.exit_code)


if __name__ == "__main__":
    cli()
