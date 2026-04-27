"""Run config, run context, and logging configuration."""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..io.file_utils import sha256_file


@dataclass
class PathConfig:
    raw_dir: Path
    staging_dir: Path
    clean_dir: Path
    analytics_dir: Path
    published_duckdb: Path
    manifests_dir: Path
    logs_dir: Path


@dataclass
class LimitConfig:
    parser_batch_size: int = 50000
    log_progress_every: int = 10000


@dataclass
class RunConfig:
    snapshot_id: str
    paths: PathConfig
    limits: LimitConfig
    config_path: Path
    config_sha256: str

    @classmethod
    def load(cls, path: str | Path) -> "RunConfig":
        p = Path(path).resolve()
        with p.open("r") as f:
            data = yaml.safe_load(f) or {}
        paths_data = data.get("paths", {})
        limits_data = data.get("limits", {})
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            paths=PathConfig(
                raw_dir=Path(paths_data["raw_dir"]),
                staging_dir=Path(paths_data["staging_dir"]),
                clean_dir=Path(paths_data["clean_dir"]),
                analytics_dir=Path(paths_data["analytics_dir"]),
                published_duckdb=Path(paths_data["published_duckdb"]),
                manifests_dir=Path(paths_data["manifests_dir"]),
                logs_dir=Path(paths_data["logs_dir"]),
            ),
            limits=LimitConfig(
                parser_batch_size=int(limits_data.get("parser_batch_size", 50000)),
                log_progress_every=int(limits_data.get("log_progress_every", 10000)),
            ),
            config_path=p,
            config_sha256=sha256_file(p),
        )


@dataclass
class RunContext:
    run_id: str
    snapshot_id: str
    config: RunConfig
    logger: logging.Logger
    raw_snapshot_dir: Path = field(init=False)
    staging_dir: Path = field(init=False)
    clean_dir: Path = field(init=False)
    analytics_dir: Path = field(init=False)
    manifest_path: Path = field(init=False)
    log_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.raw_snapshot_dir = self.config.paths.raw_dir / self.snapshot_id
        self.staging_dir = self.config.paths.staging_dir / self.run_id
        self.clean_dir = self.config.paths.clean_dir / self.run_id
        self.analytics_dir = self.config.paths.analytics_dir / self.run_id
        self.manifest_path = self.config.paths.manifests_dir / f"{self.run_id}.json"
        self.log_path = self.config.paths.logs_dir / f"{self.run_id}.log"

    def releases_xml_path(self) -> Path:
        return self.raw_snapshot_dir / "releases.xml"


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(run_id: str, config: RunConfig) -> logging.Logger:
    """Configure the discogs_etl logger with file + stderr handlers for this run."""
    log_path = config.paths.logs_dir / f"{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("discogs_etl")
    logger.setLevel(logging.INFO)
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fh = logging.FileHandler(log_path, mode="a")
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(sh)

    logger.propagate = False
    return logger
