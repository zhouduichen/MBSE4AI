"""Verification-case shape, coverage, activity branch, and orphan checks."""

from __future__ import annotations

from typing import Any, Mapping

from .common import by_id, by_kind, finding, payload, ratio, text_of


_REQUIRED_FIELDS = ("method", "pass_criteria", "requirement_ids")


def validate_verification(graph: Mapping[str, object]) -> dict[str, object]:
    verification_cases = by_kind(graph, "verification_case")
    requirements = [item for item in by_kind(graph, "requirement") if str(item.get("status", "")) in {"accepted", "validated", "locked"}]
    requirement_ids = {str(item.get("id", "")) for item in requirements}
    verified_ids: set[str] = set()
    invalid_cases: list[str] = []
    orphan_cases: list[str] = []
    for case in verification_cases:
        case_id = str(case.get("id", ""))
        item = payload(case)
        missing = [field for field in _REQUIRED_FIELDS if not item.get(field)]
        if missing:
            invalid_cases.append(case_id)
        linked = {str(value) for value in item.get("requirement_ids", ())} if isinstance(item.get("requirement_ids"), list | tuple) else set()
        linked |= {
            str(relation.get("source_id", ""))
            for relation in graph.get("relations", ())
            if isinstance(relation, Mapping)
            and str(relation.get("target_id", "")) == case_id
            and str(relation.get("predicate", "")) == "verifiedBy"
        }
        valid_linked = linked & requirement_ids
        verified_ids |= valid_linked
        if not valid_linked:
            orphan_cases.append(case_id)
    verification_coverage = ratio(len(verified_ids), len(requirements))
    test_types = {text_of(payload(item).get("test_type", payload(item).get("method", ""))).casefold() for item in verification_cases}
    required_types = {"normal", "failure", "boundary", "exception"}
    activity_text = " ".join(text_of(payload(item)) + " " + text_of(item.get("name", "")) for item in by_kind(graph, "activity"))
    activity_branch_coverage = round(sum(1 for branch in ("failure", "exception", "alternative", "boundary") if branch in activity_text.casefold()) / 4, 6) if activity_text else None
    branch_status = "N/A" if activity_branch_coverage is None else "PASS" if activity_branch_coverage >= 0.75 else "FAIL"
    return {
        "verification_case_count": len(verification_cases),
        "verification_coverage": verification_coverage,
        "invalid_verification_case_ids": invalid_cases,
        "orphan_test_case_ids": orphan_cases,
        "orphan_test_case_rate": ratio(len(orphan_cases), len(verification_cases)),
        "test_types": sorted(test_types),
        "test_type_coverage": ratio(len(test_types & required_types), len(required_types)),
        "activity_branch_coverage": activity_branch_coverage,
        "findings": [
            finding("T12", str(graph.get("project_id", "")), "PASS" if not invalid_cases else "FAIL", severity="P1", category="verification_generation", expected="each verification case has a complete structured payload", actual={"coverage": verification_coverage, "invalid": invalid_cases}, related_elements=[*invalid_cases, *orphan_cases], root_cause="verification payload is incomplete" if invalid_cases else "", recommended_fix="Emit method, precondition, input, procedure, expected result, and pass/fail criterion."),
            finding("T14", str(graph.get("project_id", "")), "N/A" if verification_coverage is None else "PASS" if verification_coverage >= 0.90 and not orphan_cases else "FAIL", severity="P0", category="verification_coverage", expected=">= 90% verifiable requirements have valid verification links and no orphan test cases", actual={"coverage": verification_coverage, "orphans": orphan_cases}, related_elements=orphan_cases, root_cause="verification cases are absent, orphaned, or not linked to requirements" if verification_coverage is not None and (verification_coverage < 0.90 or orphan_cases) else "", recommended_fix="Link every verification case to a requirement and retain its pass/fail criterion."),
            finding("T13", str(graph.get("project_id", "")), branch_status, severity="P1", category="activity_to_test_case", expected="activity decision/failure/alternative/boundary branches are represented", actual=activity_branch_coverage, root_cause="activity details are not converted to verification scenarios" if activity_branch_coverage is not None and activity_branch_coverage < 0.75 else "", recommended_fix="Generate normal, failure, boundary, and exception verification scenarios from Activity branches."),
        ],
    }
