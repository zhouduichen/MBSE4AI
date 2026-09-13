"""Predicate-aware requirement traceability matrix projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.application.projections.common import header, requirement_trace_status, trace_targets
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


@dataclass(frozen=True, slots=True)
class TraceabilityRowView:
    requirement_id: str
    requirement_name: str
    functions: tuple[str, ...]
    logical_components: tuple[str, ...]
    physical_blocks: tuple[str, ...]
    verification_cases: tuple[str, ...]
    validation_cases: tuple[str, ...]
    gaps: tuple[str, ...]
    coverage_percent: float
    status: str

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


def build_traceability_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    rows = []
    matrix = []
    for requirement in sorted((item for item in graph.entities if item.kind is EntityKind.REQUIREMENT), key=lambda item: item.id):
        status, gaps, trace = requirement_trace_status(graph, requirement)
        coverage = sum(bool(trace[key]) for key in ("functions", "logical", "physical", "verification", "validation")) / 5 * 100
        row = TraceabilityRowView(requirement.id, requirement.meta.name, trace["functions"], trace["logical"], trace["physical"], trace["verification"], trace["validation"], gaps, coverage, status)
        rows.append(row.as_dict())
        matrix.extend({"requirement_id": requirement.id, "requirement_name": requirement.meta.name, "function_id": function_id, "present": True, "predicate": "satisfiedBy"} for function_id in trace["functions"])
        if not trace["functions"]:
            matrix.append({"requirement_id": requirement.id, "requirement_name": requirement.meta.name, "function_id": None, "present": False, "predicate": "satisfiedBy"})
    return {
        **header(graph).as_dict(),
        "rows": rows,
        "requirement_function_matrix": matrix,
        "metrics": {
            "requirement_count": len(rows),
            "complete_count": sum(item["status"] == "PASS" for item in rows),
            "average_coverage_percent": round(sum(float(item["coverage_percent"]) for item in rows) / len(rows), 2) if rows else 100.0,
        },
    }
