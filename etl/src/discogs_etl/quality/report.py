"""Aggregate CheckResult lists into manifest-friendly status."""
from __future__ import annotations

from typing import Iterable

from ..pipeline.manifest import CheckResult, QualityStatus


def derive_status(results: Iterable[CheckResult]) -> QualityStatus:
    """Compute the run-level quality_checks.status from check results."""
    has_critical_fail = False
    has_warning_fail = False
    for r in results:
        if not r.passed:
            if r.severity == "critical":
                has_critical_fail = True
            elif r.severity == "warning":
                has_warning_fail = True
    if has_critical_fail:
        return "failed"
    if has_warning_fail:
        return "passed_with_warnings"
    return "passed"
