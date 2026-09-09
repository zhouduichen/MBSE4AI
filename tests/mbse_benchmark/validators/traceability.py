"""Requirement/use-case/activity/architecture/verification trace checks."""

from __future__ import annotations

from typing import Any, Mapping

from .common import by_id, by_kind, edge_map, finding, relation_map, ratio


def _accepted_requirements(graph: Mapping[str, object]) -> list[dict[str, Any]]:
    return [item for item in by_kind(graph, "requirement") if str(item.get("status", "")) in {"accepted", "validated", "locked"}]


def _has_relation(graph: Mapping[str, object], source: str, target_kinds: set[str], predicates: set[str] | None = None) -> bool:
    index = by_id(graph)
    for item in graph.get("relations", ()):
        if not isinstance(item, Mapping) or str(item.get("source_id", "")) != source:
            continue
        if predicates is not None and str(item.get("predicate", "")) not in predicates:
            continue
        if str(index.get(str(item.get("target_id", "")), {}).get("kind", "")) in target_kinds:
            return True
    return False


def _function_chain(graph: Mapping[str, object], requirement_id: str) -> tuple[bool, bool, bool, list[str]]:
    index = by_id(graph)
    functions: list[str] = []
    logical: list[str] = []
    physical: list[str] = []
    for relation in graph.get("relations", ()):
        if not isinstance(relation, Mapping) or str(relation.get("source_id", "")) != requirement_id:
            continue
        if str(relation.get("predicate", "")) != "satisfiedBy":
            continue
        target = str(relation.get("target_id", ""))
        if str(index.get(target, {}).get("kind", "")) == "function":
            functions.append(target)
    for function_id in functions:
        for relation in graph.get("relations", ()):
            if not isinstance(relation, Mapping) or str(relation.get("source_id", "")) != function_id:
                continue
            if str(relation.get("predicate", "")) != "allocatedTo":
                continue
            target = str(relation.get("target_id", ""))
            if str(index.get(target, {}).get("kind", "")) == "logical_component":
                logical.append(target)
    for logical_id in logical:
        for relation in graph.get("relations", ()):
            if not isinstance(relation, Mapping) or str(relation.get("source_id", "")) != logical_id:
                continue
            if str(relation.get("predicate", "")) != "allocatedTo":
                continue
            target = str(relation.get("target_id", ""))
            if str(index.get(target, {}).get("kind", "")) == "physical_block":
                physical.append(target)
    return bool(functions), bool(logical), bool(physical), [*functions, *logical, *physical]


def validate_traceability(graph: Mapping[str, object]) -> dict[str, object]:
    requirements = _accepted_requirements(graph)
    index = by_id(graph)
    _, incoming = edge_map(graph)
    upstream_ids = [
        str(item.get("id", "")) for item in requirements
        if item.get("source_ids")
        or incoming.get(str(item.get("id", "")))
        or any(
            isinstance(relation, Mapping)
            and str(relation.get("source_id", "")) == str(item.get("id", ""))
            and str(relation.get("predicate", "")) in {"derivedFrom", "refines", "describedBy"}
            and str(relation.get("target_id", "")) in index
            for relation in graph.get("relations", ())
        )
    ]
    use_case_ids = [
        str(item.get("id", "")) for item in requirements
        if _has_relation(graph, str(item.get("id", "")), {"use_case"}, {"derivedFrom", "refines", "validatedBy"})
        or any(str(item.get("id", "")) in (by_kind(graph, "use_case")[0].get("payload", {}).get("requirement_ids", ()) if by_kind(graph, "use_case") else ()) for _ in [0])
    ]
    activity_ids = [
        str(item.get("id", "")) for item in requirements
        if _has_relation(graph, str(item.get("id", "")), {"activity", "operational_scenario"}, {"derivedFrom", "refines", "decomposes"})
    ]
    function_ids: list[str] = []
    logical_ids: list[str] = []
    physical_ids: list[str] = []
    architecture_paths: dict[str, dict[str, object]] = {}
    verification_ids = {str(item.get("id", "")) for item in by_kind(graph, "verification_case")}
    verification_linked: list[str] = []
    for requirement in requirements:
        requirement_id = str(requirement.get("id", ""))
        has_function, has_logical, has_physical, path = _function_chain(graph, requirement_id)
        if path:
            function_ids.append(requirement_id)
            if has_logical:
                logical_ids.append(requirement_id)
            if has_physical:
                physical_ids.append(requirement_id)
        architecture_paths[requirement_id] = {
            "function": has_function,
            "logical": has_logical,
            "physical": has_physical,
            "path": path,
        }
        if any(
            str(item.get("source_id", "")) == requirement_id and str(item.get("target_id", "")) in verification_ids
            for item in graph.get("relations", ()) if isinstance(item, Mapping)
        ):
            verification_linked.append(requirement_id)
    total = len(requirements)
    upstream = ratio(len(upstream_ids), total)
    architecture = ratio(len(physical_ids), total)
    verification = ratio(len(verification_linked), total)
    use_case_activity = ratio(len(set(use_case_ids) & set(activity_ids)), total)
    complete = [
        item for item in requirements
        if str(item.get("id", "")) in upstream_ids
        and str(item.get("id", "")) in activity_ids
        and str(item.get("id", "")) in physical_ids
        and str(item.get("id", "")) in verification_linked
    ]
    end_to_end = ratio(len(complete), total)
    return {
        "upstream_traceability": upstream,
        "use_case_traceability": ratio(len(use_case_ids), total),
        "activity_traceability": ratio(len(activity_ids), total),
        "use_case_activity_consistency": use_case_activity,
        "architecture_traceability": architecture,
        "verification_coverage": verification,
        "end_to_end_traceability": end_to_end,
        "trace_paths": architecture_paths,
        "complete_requirement_ids": [str(item.get("id", "")) for item in complete],
        "broken_requirement_ids": [str(item.get("id", "")) for item in requirements if str(item.get("id", "")) not in {str(item.get("id", "")) for item in complete}],
        "findings": [
            finding("T5", str(graph.get("project_id", "")), "PASS" if upstream >= 0.95 else "FAIL", severity="P0", category="upstream_traceability", expected=">= 95% requirements with valid upstream trace", actual=upstream, root_cause="requirements have no valid source relation or source ID" if upstream < 0.95 else "", recommended_fix="Preserve Stakeholder/Scenario provenance on every requirement."),
            finding("T6/T7", str(graph.get("project_id", "")), "PASS" if use_case_activity >= 0.90 else "FAIL", severity="P1", category="use_case_activity_consistency", expected=">= 90% requirement/use-case/activity consistency", actual={"use_case": ratio(len(use_case_ids), total), "activity": ratio(len(activity_ids), total), "consistency": use_case_activity}, root_cause="use cases or activities do not link to requirements" if use_case_activity < 0.90 else "", recommended_fix="Populate explicit Requirement ↔ Use Case ↔ Activity relations and branch payloads."),
            finding("T11", str(graph.get("project_id", "")), "PASS" if architecture >= 0.90 else "NOT_IMPLEMENTED" if not by_kind(graph, "logical_component") or not by_kind(graph, "physical_block") else "FAIL", severity="P0", category="architecture_traceability", expected=">= 90% Requirement → Function → Logical → Physical paths", actual=architecture, root_cause="RFLP layers or typed allocation links are missing" if architecture < 0.90 else "", recommended_fix="Add typed satisfy/allocate/realize relations while preserving requirement IDs."),
            finding("T12/T14", str(graph.get("project_id", "")), "PASS" if verification >= 0.90 else "FAIL", severity="P0", category="verification_traceability", expected=">= 90% verifiable requirements have valid verification", actual=verification, root_cause="verification cases are absent or orphaned" if verification < 0.90 else "", recommended_fix="Generate structured VerificationCase objects linked to each requirement."),
            finding("T15", str(graph.get("project_id", "")), "PASS" if end_to_end >= 0.85 else "FAIL", severity="P0", category="end_to_end_traceability", expected=">= 85% complete end-to-end traces", actual=end_to_end, related_elements=[str(item.get("id", "")) for item in requirements if str(item.get("id", "")) not in {str(item.get("id", "")) for item in complete}], root_cause="trace breaks between upstream behavior and downstream architecture/verification" if end_to_end < 0.85 else "", recommended_fix="Repair the earliest broken relation and rerun downstream phases."),
        ],
    }
