"""Canonical three-state coverage semantics."""

from __future__ import annotations

from enum import StrEnum
from typing import Mapping


class CoverageStatus(StrEnum):
    """Stable wire values for coverage results."""

    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


def coverage_result(
    covered_count: int,
    total_count: int,
    *,
    passed: bool | None = None,
) -> Mapping[str, object]:
    """Return a canonical coverage result for a finite scoped population.

    An empty population is deliberately not a ratio.  It is represented as
    N/A so consumers cannot mistake the absence of requirements for complete
    coverage.
    """

    covered = max(0, int(covered_count))
    total = max(0, int(total_count))
    if total == 0:
        return {
            "covered_count": 0,
            "requirement_count": 0,
            "coverage": None,
            "status": CoverageStatus.NOT_APPLICABLE.value,
            "passed": False,
        }
    covered = min(covered, total)
    ratio = covered / total
    is_passed = covered == total if passed is None else bool(passed)
    return {
        "covered_count": covered,
        "requirement_count": total,
        "coverage": ratio,
        "status": (
            CoverageStatus.PASS.value
            if is_passed
            else CoverageStatus.FAIL.value
        ),
        "passed": is_passed,
    }


__all__ = ["CoverageStatus", "coverage_result"]
