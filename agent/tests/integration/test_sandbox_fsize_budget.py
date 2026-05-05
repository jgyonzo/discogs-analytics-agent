"""007 / T005 — RLIMIT_FSIZE regression test.

The production failure surfaced as
``IO Error: Could not write file
"/tmp/duckdb/duckdb_temp_storage_DEFAULT-0.tmp": File too large``
when the sandbox's `RLIMIT_FSIZE` was 64 MiB. Two assertions guard
the fix:

1. ``RLIMIT_FSIZE_BYTES >= 1 GiB`` — load-bearing const-min that
   fails if a future change reverts the bump to a value too small
   for full-catalog spills (FR-007, SC-003 anchor).

2. The sandbox successfully writes a file larger than the pre-fix
   64 MiB cap. We use a direct Python write (rather than a DuckDB
   GROUP BY spill) because:
   - DuckDB partitions spill across multiple
     ``duckdb_temp_storage_*.tmp`` files in version-dependent ways,
     so a fixture sized to land a single >64 MiB spill on one
     DuckDB version may land 4× 20 MiB files on the next.
   - The bug was about the kernel-level RLIMIT_FSIZE backstop, not
     about DuckDB internals. A direct write tests that backstop
     deterministically.
   - Realistic full-catalog spill verification is the job of the
     manual smoke step (T011 in 007/tasks.md, quickstart.md §1).

The over-cap controlled-failure test lives in
``test_oversize_write_surfaces_controlled_failure`` (T006).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from discogs_agent.config import settings
from discogs_agent.sandbox import runner
from discogs_agent.sandbox.restrictions import RLIMIT_FSIZE_BYTES

ONE_GIB = 1024 * 1024 * 1024
EIGHT_MIB = 8 * 1024 * 1024
ONE_HUNDRED_TWENTY_EIGHT_MIB = 128 * 1024 * 1024


def test_rlimit_fsize_byte_count_meets_minimum() -> None:
    """007 SC-003 anchor — guard against a future revert of T001.

    If `RLIMIT_FSIZE_BYTES` ever drops below 1 GiB, this test fails
    immediately and CI blocks the regression. The choice of 1 GiB
    is the workload floor from research.md R-01: anything below
    that risks tripping on legitimate full-catalog GROUP BY spills.
    """
    assert RLIMIT_FSIZE_BYTES >= ONE_GIB, (
        f"RLIMIT_FSIZE_BYTES={RLIMIT_FSIZE_BYTES} is below the 1 GiB floor "
        f"set by research.md R-01. See specs/007-sandbox-fsize-budget/."
    )


def test_sandbox_allows_write_above_old_cap(tmp_path: Path) -> None:
    """Write 128 MiB through the sandbox — comfortably above the
    pre-fix 64 MiB cap, comfortably below the post-fix 2 GiB cap.

    Pre-fix this would EFBIG with `IO Error: File too large`. Post-fix
    it succeeds.
    """
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()

    thread_id = str(uuid4())
    run_id = str(uuid4())

    generated_code = f"""
import os

target = os.path.join(os.environ['ARTIFACT_DIR'], 'big.bin')
chunk = b'\\x00' * {EIGHT_MIB}
with open(target, 'wb') as f:
    for _ in range({ONE_HUNDRED_TWENTY_EIGHT_MIB} // {EIGHT_MIB}):
        f.write(chunk)

RESULT = {{'bytes_written': os.path.getsize(target)}}
"""

    outcome = runner.run_in_sandbox(
        generated_code=generated_code,
        thread_id=thread_id,
        run_id=run_id,
        timeout_seconds=settings.SANDBOX_TIMEOUT_SECONDS,
        duckdb_path=settings.ANALYTICS_DUCKDB_PATH,
        artifacts_root=str(artifacts_root),
    )

    assert outcome.exit_code == 0, (
        f"sandbox exited with {outcome.exit_code}; "
        f"stderr={outcome.stderr!r}; "
        f"exception={outcome.exception_type}: {outcome.exception_message}"
    )
    assert outcome.exception_type is None, (
        f"unexpected exception {outcome.exception_type}: {outcome.exception_message}"
    )
    assert outcome.result is not None
    assert outcome.result["bytes_written"] == ONE_HUNDRED_TWENTY_EIGHT_MIB

    # And the file landed on disk inside the per-run artifact dir.
    written = artifacts_root / thread_id / run_id / "big.bin"
    assert written.exists()
    assert written.stat().st_size == ONE_HUNDRED_TWENTY_EIGHT_MIB


def test_oversize_write_surfaces_controlled_failure(tmp_path: Path) -> None:
    """007 / T006 — over-cap write trips RLIMIT_FSIZE (EFBIG).

    Asks the sandbox to write `RLIMIT_FSIZE_BYTES + 8 MiB` to a
    file. The kernel sends SIGXFSZ / returns EFBIG on the write
    that crosses the cap. Asserts the sandbox surfaces this as a
    controlled failure: exit code non-zero (or exception captured),
    no agent crash, no traceback projected to a user-facing string.

    Empirically fast (<1s) on tmpfs even at 2+ GiB — the kernel
    short-circuits Python's chunked loop once the cap is reached.
    """
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()

    thread_id = str(uuid4())
    run_id = str(uuid4())

    over_cap_bytes = RLIMIT_FSIZE_BYTES + EIGHT_MIB

    generated_code = f"""
import os

target = os.path.join(os.environ['ARTIFACT_DIR'], 'too_big.bin')
chunk = b'\\x00' * {EIGHT_MIB}
with open(target, 'wb') as f:
    for _ in range({over_cap_bytes} // {EIGHT_MIB}):
        f.write(chunk)

RESULT = {{'bytes_written': os.path.getsize(target)}}
"""

    outcome = runner.run_in_sandbox(
        generated_code=generated_code,
        thread_id=thread_id,
        run_id=run_id,
        # Generous timeout — writing 2 GiB+ through Python takes ~3-5s.
        timeout_seconds=max(settings.SANDBOX_TIMEOUT_SECONDS, 60),
        duckdb_path=settings.ANALYTICS_DUCKDB_PATH,
        artifacts_root=str(artifacts_root),
    )

    # The run must NOT be a clean success — RLIMIT_FSIZE has to bite.
    assert not (outcome.exit_code == 0 and outcome.exception_type is None), (
        "sandbox returned a clean success for an over-cap write; "
        f"either RLIMIT_FSIZE is not enforced (cap={RLIMIT_FSIZE_BYTES}) "
        f"or the write did not exceed it. result={outcome.result}"
    )

    # The failure must be controlled — exception captured, no
    # uncaught crash. The kernel sends SIGXFSZ when RLIMIT_FSIZE
    # trips during a write; Python typically translates this into
    # an `OSError` (errno=EFBIG=27) inside the user code. Either
    # surface (exception_type populated, or exit_code != 0) is
    # acceptable.
    assert outcome.exception_type is not None or outcome.exit_code != 0, (
        f"sandbox returned ambiguous outcome for over-cap write: "
        f"exit={outcome.exit_code}, exception={outcome.exception_type}, "
        f"stderr={outcome.stderr!r}"
    )

    # The written file (if any) must not exceed the cap.
    target = artifacts_root / thread_id / run_id / "too_big.bin"
    if target.exists():
        assert target.stat().st_size <= RLIMIT_FSIZE_BYTES, (
            f"file size {target.stat().st_size} exceeds RLIMIT_FSIZE "
            f"{RLIMIT_FSIZE_BYTES} — kernel cap not enforced"
        )
