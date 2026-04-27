"""Run manifest persistence per contracts/manifest.md."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..io.file_utils import atomic_replace


QualityStatus = Literal["passed", "passed_with_warnings", "failed", "incomplete"]


@dataclass
class CheckResult:
    name: str
    layer: str
    table: str
    severity: Literal["critical", "warning"]
    passed: bool
    details: str | None = None


class Manifest:
    """In-memory manifest with atomic save() to JSON.

    Schema: see specs/001-discogs-etl/contracts/manifest.md.
    """

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self._data = data
        self._path = Path(path)

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        run_id: str,
        snapshot_id: str,
        etl_version: str,
        started_at: str,
        config_path: str | Path,
        config_sha256: str,
    ) -> "Manifest":
        data: dict[str, Any] = {
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "etl_version": etl_version,
            "started_at": started_at,
            "finished_at": None,
            "config": {
                "config_path": str(config_path),
                "config_sha256": config_sha256,
            },
            "source_files": {},
            "step_durations": {},
            "outputs": {
                "staging": {},
                "clean": {},
                "analytics": {},
                "published": {},
            },
            "quality_checks": {
                "status": "incomplete",
                "warnings": [],
                "results": [],
            },
        }
        m = cls(data, Path(path))
        m.save()
        return m

    @classmethod
    def load(cls, path: str | Path) -> "Manifest":
        p = Path(path)
        with p.open("r") as f:
            return cls(json.load(f), p)

    def record_source_file(
        self,
        name: str,
        *,
        path: str | Path,
        size_bytes: int,
        checksum: str,
    ) -> None:
        self._data["source_files"][name] = {
            "path": str(path),
            "size_bytes": int(size_bytes),
            "checksum": f"sha256:{checksum}",
        }

    def record_step_duration(self, step_name: str, seconds: float) -> None:
        self._data["step_durations"][step_name] = round(float(seconds), 4)

    def record_output(
        self,
        layer: Literal["staging", "clean", "analytics", "published"],
        table: str,
        *,
        path: str | Path,
        row_count: int | None = None,
        **extras: Any,
    ) -> None:
        entry: dict[str, Any] = {"path": str(path)}
        if row_count is not None:
            entry["row_count"] = int(row_count)
        entry.update(extras)
        self._data["outputs"].setdefault(layer, {})[table] = entry

    def record_check_result(self, result: CheckResult) -> None:
        self._data["quality_checks"]["results"].append(
            {
                "name": result.name,
                "layer": result.layer,
                "table": result.table,
                "severity": result.severity,
                "passed": bool(result.passed),
                "details": result.details,
            }
        )
        if not result.passed and result.severity == "warning":
            self._data["quality_checks"]["warnings"].append(
                {"name": result.name, "details": result.details}
            )

    def warn(self, name: str, details: str | None = None) -> None:
        """Add a free-standing warning (not tied to a check result)."""
        self._data["quality_checks"]["warnings"].append(
            {"name": name, "details": details}
        )

    def set_quality_status(self, status: QualityStatus) -> None:
        self._data["quality_checks"]["status"] = status

    def finalize(self, finished_at: str) -> None:
        self._data["finished_at"] = finished_at

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @property
    def quality_status(self) -> QualityStatus:
        return self._data["quality_checks"]["status"]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w") as f:
            json.dump(self._data, f, indent=2, sort_keys=False)
        atomic_replace(tmp, self._path)
