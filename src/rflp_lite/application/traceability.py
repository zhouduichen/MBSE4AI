"""Trace matrix construction and coverage reporting."""

from __future__ import annotations

from rflp_lite.domain.canonical import canonical_hash


def _row(source_id: str, predicate: str, target_id: str, status: str = "candidate", producer: str = "rule") -> dict[str, object]:
    return {
        "id": f"trace-{canonical_hash((source_id, predicate, target_id))[:12]}",
        "source_id": source_id,
        "predicate": predicate,
        "target_id": target_id,
        "status": status,
        "producer": producer,
    }


def build_trace_matrix(state: dict[str, object]) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    requirements = tuple(state.get("structured_requirements", ()))
    claims = tuple(state.get("claims", ()))
    for requirement in requirements:
        requirement_id = str(requirement.get("id", ""))
        source_id = str(requirement.get("source_region_id", ""))
        if source_id and requirement_id:
            rows.append(_row(source_id, "derivedFrom", requirement_id, str(requirement.get("status", "candidate")), str(requirement.get("producer", "rule"))))
        related_claims = [item for item in claims if item.get("structured_requirement_id") == requirement_id]
        for claim in related_claims:
            claim_id = str(claim.get("id", ""))
            if claim_id:
                rows.append(_row(requirement_id, "representedBy", claim_id, str(claim.get("status", "candidate")), str(claim.get("producer", "rule"))))
            if claim.get("status") != "accepted":
                continue
            rflp = state.get("rflp") or {}
            targets = [
                item for item in rflp.get("elements", ())
                if item.get("layer") == "R"
                and any(key == "claim_id" and value == claim_id for key, value in item.get("attributes", ()))
            ]
            for target in targets:
                rows.append(_row(requirement_id, "satisfiedBy", str(target.get("id", "")), "accepted", "rflp"))
    for attribute in state.get("requirement_attributes", ()):
        if not isinstance(attribute, dict) or attribute.get("status") != "accepted":
            continue
        requirement_id = str(attribute.get("requirement_id", "")); attribute_id = str(attribute.get("id", ""))
        if requirement_id and attribute_id:
            rows.append(_row(requirement_id, "representedBy", attribute_id, "accepted", str(attribute.get("producer", "rule"))))
    for constraint in state.get("requirement_constraints", ()):
        if not isinstance(constraint, dict) or constraint.get("status") != "accepted":
            continue
        for requirement_id in constraint.get("requirement_ids", ()):
            if str(requirement_id) and constraint.get("id"):
                rows.append(_row(str(requirement_id), "constrainedBy", str(constraint["id"]), "accepted", str(constraint.get("producer", "rule"))))
    for suggestion in state.get("retrieval_suggestions", ()):
        if not isinstance(suggestion, dict) or suggestion.get("status") != "accepted":
            continue
        record_id = str(suggestion.get("record_id", ""))
        requirement_id = str(suggestion.get("requirement_id", suggestion.get("target_requirement_id", "")))
        if record_id and requirement_id:
            rows.append(_row(record_id, "similarTo", requirement_id, "accepted", str(suggestion.get("producer", "retrieval"))))
    mbse = state.get("mbse") or {}
    for link in mbse.get("trace_links", ()):
        source_id = str(link.get("source_id", ""))
        target_id = str(link.get("target_id", ""))
        if source_id and target_id:
            rows.append(_row(source_id, str(link.get("predicate", "refines")), target_id, str(link.get("status", "candidate")), "mbse"))
    for group in ("use_cases", "activities", "messages"):
        for item in mbse.get(group, ()):
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("id", ""))
            if str(item.get("status", "accepted")) != "accepted" or not entity_id:
                continue
            for requirement_id in item.get("requirement_ids", ()):
                if str(requirement_id):
                    rows.append(_row(str(requirement_id), "refines", entity_id, "accepted", "mbse"))
    return tuple(sorted({str(item["id"]): item for item in rows}.values(), key=lambda item: (str(item["source_id"]), str(item["predicate"]), str(item["target_id"]))))


def trace_coverage(matrix: tuple[dict[str, object], ...] | list[dict[str, object]], total: int | None = None) -> dict[str, int]:
    rows = tuple(matrix)
    requirement_ids = {
        str(row["target_id"])
        for row in rows
        if row.get("predicate") == "derivedFrom"
    }
    total_count = int(total if total is not None else len(requirement_ids))
    if total_count == 0:
        return {"source_complete": 0, "rflp_complete": 0, "mbse_complete": 0, "total": 0}
    source_ids = {str(row["target_id"]) for row in rows if row.get("predicate") == "derivedFrom"}
    rflp_ids = {str(row["source_id"]) for row in rows if row.get("predicate") == "satisfiedBy"}
    mbse_ids = {str(row["source_id"]) for row in rows if row.get("predicate") in {"refines", "realizes"}}
    return {
        "source_complete": round(len(source_ids) * 100 / total_count),
        "rflp_complete": round(len(rflp_ids) * 100 / total_count),
        "mbse_complete": round(len(mbse_ids) * 100 / total_count),
        "total": total_count,
    }


def refresh_traceability(state: dict[str, object]) -> dict[str, object]:
    from rflp_lite.domain.canonical import canonical_json
    import json

    result = json.loads(canonical_json(state))
    matrix = build_trace_matrix(result)
    result["trace_links"] = list(matrix)
    result["traceability"] = list(matrix)
    result["trace_coverage"] = trace_coverage(matrix, len(result.get("structured_requirements", ())))
    result["trace_diagnostics"] = trace_diagnostics(result, matrix)
    return result


def trace_diagnostics(state: dict[str, object], matrix: tuple[dict[str, object], ...] | list[dict[str, object]]) -> list[dict[str, object]]:
    rows = tuple(matrix)
    diagnostics: list[dict[str, object]] = []
    for requirement in state.get("structured_requirements", ()):
        if not isinstance(requirement, dict) or requirement.get("status") != "accepted":
            continue
        requirement_id = str(requirement.get("id", ""))
        if requirement_id and not any(row.get("source_id") == requirement_id and row.get("predicate") in {"satisfiedBy", "refines"} for row in rows):
            diagnostics.append({"code": "requirement_without_model", "source_id": requirement_id})
    return diagnostics
