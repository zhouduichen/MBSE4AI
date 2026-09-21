"""Predicate-aware requirement traceability matrix projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.application.projections.common import header, requirement_trace_status
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.coverage_status import coverage_result
from rflp_lite.methodology.vertical_coverage import resolve_requirement_trace


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
    coverage_percent: float | None
    coverage_status: str
    status: str
    stage_coverage: Mapping[str, bool]
    primary_path: tuple[str, ...]

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


def build_traceability_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    rows = []
    matrix = []
    for requirement in sorted((item for item in graph.entities if item.kind is EntityKind.REQUIREMENT), key=lambda item: item.id):
        status, gaps, trace = requirement_trace_status(graph, requirement)
        canonical = resolve_requirement_trace(graph, requirement.id)
        coverage = sum(canonical.stage_coverage.values()) / 5 * 100
        coverage_status = "pass" if canonical.complete else "fail"
        row = TraceabilityRowView(
            requirement.id,
            requirement.meta.name,
            trace["functions"],
            trace["logical"],
            trace["physical"],
            trace["verification"],
            trace["validation"],
            gaps,
            coverage,
            coverage_status,
            status,
            dict(canonical.stage_coverage),
            canonical.primary_path,
        )
        rows.append(row.as_dict())
        matrix.extend({"requirement_id": requirement.id, "requirement_name": requirement.meta.name, "function_id": function_id, "present": True, "predicate": "satisfiedBy"} for function_id in trace["functions"])
        if not trace["functions"]:
            matrix.append({"requirement_id": requirement.id, "requirement_name": requirement.meta.name, "function_id": None, "present": False, "predicate": "satisfiedBy"})
    complete_count = sum(item["coverage_status"] == "pass" for item in rows)
    aggregate = coverage_result(complete_count, len(rows))
    average = (
        round(sum(float(item["coverage_percent"]) for item in rows if item["coverage_percent"] is not None) / len(rows), 2)
        if rows
        else None
    )
    return {
        **header(graph).as_dict(),
        "rows": rows,
        "requirement_function_matrix": matrix,
        "metrics": {
            "requirement_count": len(rows),
            "covered_count": complete_count,
            "complete_count": sum(item["status"] == "PASS" for item in rows),
            "coverage": aggregate["coverage"],
            "status": aggregate["status"],
            "coverage_status": aggregate["status"],
            "average_coverage_percent": average,
        },
    }
