"""Run-id, checksum, and atomic-replace helpers."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path


def make_run_id() -> str:
    """Sortable UTC timestamp run id, filename-safe (microsecond precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")


def sha256_file(path: str | Path, *, buf_size: int = 1 << 20) -> str:
    """SHA-256 hex digest computed via streaming reads."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(buf_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def atomic_replace(src: str | Path, dst: str | Path) -> None:
    """Atomic rename src -> dst. Both must live on the same filesystem."""
    src_path = Path(src)
    dst_path = Path(dst)
    src_dev = os.stat(src_path.parent).st_dev
    dst_parent = dst_path.parent
    dst_parent.mkdir(parents=True, exist_ok=True)
    dst_dev = os.stat(dst_parent).st_dev
    if src_dev != dst_dev:
        raise OSError(
            f"atomic_replace requires same filesystem: src dev={src_dev}, dst dev={dst_dev}"
        )
    os.replace(src_path, dst_path)
