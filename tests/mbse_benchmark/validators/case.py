"""Compose all deterministic checks for one observed case result."""

from __future__ import annotations

from typing import Any, Mapping

from rflp_lite.methodology.coverage_status import coverage_result

from .architecture import validate_architecture
from .common import finding, validate_structural_graph
from .consistency import validate_consistency
from .coverage import validate_coverage
from .regression import validate_regression
from .requirements import validate_requirements
from .traceability import validate_traceability
from .verification import validate_verification


def validate_case(
    case: Mapping[str, object],
    raw_result: Mapping[str, object],
    expectations: Mapping[str, object],
    *,
    repeats: list[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    case_id = str(case.get("case_id", ""))
    graph = raw_result.get("graph", {})
    if not isinstance(graph, Mapping) or not graph:
        blocked = raw_result.get("execution", {})
        status = str(blocked.get("status", "failed")) if isinstance(blocked, Mapping) else "failed"
        empty_coverage = coverage_result(0, 0)
        return {
            "case_id": case_id,
            "metrics": {
                "requirement_count": empty_coverage["requirement_count"],
                "covered_count": empty_coverage["covered_count"],
                "coverage": empty_coverage["coverage"],
                "coverage_status": empty_coverage["status"],
                "trace_accuracy": None,
                "RFLP_coverage": None,
            },
            "details": {"coverage": empty_coverage},
            "findings": [finding("EXECUTION", case_id, "BLOCKED" if status == "blocked" else "FAIL", severity="P0", category="execution", expected="real system produces a ModelGraph", actual=blocked, root_cause="no observed model was produced" if status != "blocked" else "execution exceeded bounded timeout", recommended_fix="Fix the execution/runtime blocker before evaluating semantic quality.")],
        }
    structural = validate_structural_graph(graph)
    coverage = validate_coverage(case, graph, expectations)
    requirements = validate_requirements(graph, expectations)
    traceability = validate_traceability(graph)
    architecture = validate_architecture(graph, case)
    verification = validate_verification(graph)
    consistency = validate_consistency(case, graph, raw_result, expectations)
    regression = validate_regression(repeats or [raw_result], case_id) if repeats is not None else {"regression_stability": 0.0, "findings": []}
    findings = [
        *structural,
        *coverage.get("findings", ()),
        *requirements.get("findings", ()),
        *traceability.get("findings", ()),
        *architecture.get("findings", ()),
        *verification.get("findings", ()),
        *consistency.get("findings", ()),
        *regression.get("findings", ()),
    ]
    metrics = {
        "stakeholder_coverage": coverage.get("stakeholder_coverage"),
        "lifecycle_coverage": coverage.get("lifecycle_coverage"),
        "scenario_recall": coverage.get("scenario_recall"),
        "requirement_validity": requirements.get("requirement_validity"),
        "requirement_atomicity": requirements.get("requirement_atomicity"),
        "requirement_verifiability": requirements.get("requirement_verifiability"),
        "unsupported_hard_assumption_rate": requirements.get("unsupported_hard_assumption_rate"),
        "upstream_traceability": traceability.get("upstream_traceability"),
        "use_case_activity_consistency": traceability.get("use_case_activity_consistency"),
        "derived_requirement_precision": requirements.get("derived_requirement_precision"),
        "architecture_traceability": traceability.get("architecture_traceability"),
        "verification_coverage": traceability.get("verification_coverage"),
        "end_to_end_traceability": traceability.get("end_to_end_traceability"),
        "trace_accuracy": traceability.get("end_to_end_traceability"),
        "RFLP_coverage": traceability.get("architecture_traceability"),
        "orphan_element_rate": architecture.get("orphan_element_rate"),
        "known_conflict_detection": consistency.get("known_conflict_detection", 1.0 if case_id != "CASE-05" else 0.0),
        "regression_stability": regression.get("regression_stability", 0.0),
        "orphan_test_case_rate": verification.get("orphan_test_case_rate"),
        "activity_branch_coverage": verification.get("activity_branch_coverage"),
        "iteration_signal": consistency.get("iteration_signal", False),
    }
    statuses = {str(item.get("status", "")) for item in findings if isinstance(item, Mapping)}
    return {
        "case_id": case_id,
        "metrics": metrics,
        "details": {
            "coverage": coverage,
            "requirements": requirements,
            "traceability": traceability,
            "architecture": architecture,
            "verification": verification,
            "consistency": consistency,
            "regression": regression,
        },
        "findings": findings,
        "status": "FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS",
    }
