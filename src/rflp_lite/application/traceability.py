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
    mbse = state.get("mbse") or {}
    for link in mbse.get("trace_links", ()):
        source_id = str(link.get("source_id", ""))
        target_id = str(link.get("target_id", ""))
        if source_id and target_id:
            rows.append(_row(source_id, str(link.get("predicate", "refines")), target_id, str(link.get("status", "candidate")), "mbse"))
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
    return result

