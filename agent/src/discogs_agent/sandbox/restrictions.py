"""Restrictions applied to the sandbox subprocess.

`preexec_fn` builder + minimal env allowlist. macOS lacks RLIMIT_NPROC
support in the same form as Linux; we set what the platform supports
and skip the rest with a warning.
"""

from __future__ import annotations

import os
import resource
from collections.abc import Callable

# Bytes — caps the size of any single file the subprocess can write.
# RLIMIT_FSIZE is process-wide on Linux, so this single ceiling is
# shared between the chart artifact and DuckDB's spill files at
# `/tmp/duckdb/duckdb_temp_storage_*.tmp`. The previous 64 MiB value
# was sized for the chart HTML alone and tripped EFBIG on every
# release-grain GROUP BY against the published catalog (named
# incident: 007-sandbox-fsize-budget). 2 GiB sits at ~2-4× the
# worst-case full-catalog spill estimate and comfortably below the
# host tmpfs default — see contract §3.1.1 and 007/research.md R-01..R-03
# for the full sizing rationale. The cwd jail (per-run artifact dir)
# remains the *primary* write-confinement control; this rlimit is
# the *secondary* runaway-write backstop.
RLIMIT_FSIZE_BYTES = 2 * 1024 * 1024 * 1024


def make_preexec(timeout_seconds: int) -> Callable[[], None]:
    """Build a preexec_fn that applies resource limits before exec()."""

    def preexec() -> None:
        # New process group so we can SIGKILL the whole tree on timeout.
        try:
            os.setsid()
        except OSError:
            pass

        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (timeout_seconds + 5, timeout_seconds + 5),
            )
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (RLIMIT_FSIZE_BYTES, RLIMIT_FSIZE_BYTES),
            )
        except (ValueError, OSError):
            pass
        # RLIMIT_NPROC: Linux-only; macOS would EINVAL.
        if hasattr(resource, "RLIMIT_NPROC"):
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            except (ValueError, OSError):
                pass

    return preexec


def clean_env(*, duckdb_path: str, artifact_dir: str) -> dict[str, str]:
    """Build the minimal environment for the sandbox subprocess.

    Strips OPENAI_API_KEY, DATABASE_URL, AWS_*, etc. — only the
    explicitly-allowlisted variables are passed.
    """
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "ANALYTICS_DUCKDB_PATH": duckdb_path,
        "ARTIFACT_DIR": artifact_dir,
    }
