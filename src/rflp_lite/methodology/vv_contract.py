"""Shared contract for executable verification and validation plans."""

from __future__ import annotations

from collections.abc import Mapping


VV_PLAN_FIELDS = (
    "method",
    "verification_objective",
    "precondition",
    "test_condition",
    "input",
    "stimulus",
    "procedure",
    "expected_result",
    "pass_criteria",
)


def missing_vv_plan_fields(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return required executable-plan fields that are absent or blank."""

    return tuple(
        field
        for field in VV_PLAN_FIELDS
        if not str(payload.get(field, "") or "").strip()
    )


__all__ = ["VV_PLAN_FIELDS", "missing_vv_plan_fields"]
