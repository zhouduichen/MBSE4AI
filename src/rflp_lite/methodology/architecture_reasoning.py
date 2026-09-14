"""Stable, JSON-compatible reasoning payloads for logical and physical models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from rflp_lite.domain.canonical import to_primitive
from rflp_lite.domain.errors import ContractViolation

from .architecture_synthesis import ArchitectureSynthesis, PhysicalFeasibilityRow


_LOGICAL_SELECTION_STATUSES = frozenset({
    "generated", "selected", "needs_review", "blocked",
})
_PHYSICAL_STATUSES = frozenset({
    "feasible", "infeasible", "needs_measurement",
})


def logical_reasoning_payload(
    synthesis: ArchitectureSynthesis,
    *,
    function_ids: Sequence[str],
    functional_flow_ids: Sequence[str],
    dependency_pairs: Sequence[Sequence[str]],
    shared_state: Sequence[str],
    timing_constraints: Sequence[str],
    selected_alternative: str = "",
    selection_status: str = "needs_review",
    names: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    """Build the persisted explanation for one logical component."""

    selected = _ids(function_ids, "function_ids")
    flows = _ids(functional_flow_ids, "functional_flow_ids")
    pairs = _pairs(dependency_pairs, selected)
    shared = _strings(shared_state, "shared_state")
    timing = _strings(timing_constraints, "timing_constraints")
    status = str(selection_status).strip()
    if status not in _LOGICAL_SELECTION_STATUSES:
        raise ContractViolation(f"unsupported logical selection status: {status}")
    alternative = str(selected_alternative).strip()
    alternatives = tuple(synthesis.logical_candidates)
    alternative_ids = {item.alternative for item in alternatives}
    if alternative and alternative not in alternative_ids:
        raise ContractViolation(f"unknown logical architecture alternative: {alternative}")
    return {
        "basis": {
            "function_ids": selected,
            "functional_flow_ids": flows,
            "dependency_pairs": pairs,
            "shared_state": shared,
            "timing_constraints": timing,
        },
        "alternatives": [
            _copy(item.as_dict(names)) for item in alternatives
        ],
        "recommended_alternative": (
            alternatives[0].alternative if alternatives else ""
        ),
        "selected_alternative": alternative,
        "selection_status": status,
    }


def physical_reasoning_payload(row: PhysicalFeasibilityRow) -> Mapping[str, object]:
    """Build the persisted feasibility explanation for one physical block."""

    physical_id = str(row.physical_id).strip()
    if not physical_id:
        raise ContractViolation("physical reasoning requires a physical_id")
    if row.status not in _PHYSICAL_STATUSES:
        raise ContractViolation(f"unsupported physical feasibility status: {row.status}")
    value = row.as_dict()
    return {
        "physical_id": physical_id,
        "requirement_ids": _ids(value["requirement_ids"], "requirement_ids"),
        "logical_ids": _ids(value["logical_ids"], "logical_ids"),
        "function_ids": _ids(value["function_ids"], "function_ids"),
        "propagated_constraints": _copy(value["propagated_constraints"]),
        "missing_fields": _strings(value["missing_fields"], "missing_fields"),
        "conflicts": _copy(value["conflicts"]),
        "status": row.status,
        "score": float(row.score),
        "resolution_options": _copy(value["resolution_options"]),
    }


def _ids(values: Sequence[object], field: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ContractViolation(f"{field} must be an array of canonical ids")
    result = []
    for value in values:
        item = str(value).strip()
        if not item:
            raise ContractViolation(f"{field} contains an empty id")
        result.append(item)
    return list(dict.fromkeys(result))


def _strings(values: Sequence[object], field: str) -> list[str]:
    return _ids(values, field)


def _pairs(values: Sequence[Sequence[str]], function_ids: Sequence[str]) -> list[list[str]]:
    allowed = set(function_ids)
    result = []
    for value in values:
        if isinstance(value, (str, bytes)) or len(value) != 2:
            raise ContractViolation("dependency_pairs must contain pairs")
        pair = [str(item).strip() for item in value]
        if any(not item for item in pair) or any(item not in allowed for item in pair):
            raise ContractViolation("dependency_pairs must reference function_ids")
        result.append(pair)
    return [list(pair) for pair in sorted({tuple(pair) for pair in result})]


def _copy(value: object) -> object:
    try:
        return to_primitive(value)
    except TypeError as exc:
        raise ContractViolation(f"reasoning payload is not JSON-compatible: {exc}") from exc
