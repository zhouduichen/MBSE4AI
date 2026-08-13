"""Accepted semantic graph and conservative compatibility bridge."""

from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json


def _accepted_items(state: dict[str, object]) -> list[dict[str, object]]:
    discovery = state.get("discovery", {})
    groups = discovery.get("candidate_sets", []) if isinstance(discovery, dict) else []
    return [
        item
        for group in groups if isinstance(groups, list) and isinstance(group, dict)
        for item in group.get("items", []) if isinstance(group.get("items"), list) and isinstance(item, dict) and item.get("status") == "accepted"
    ]


def build_accepted_graph(state: dict[str, object]) -> dict[str, object]:
    items = _accepted_items(state)
    accepted_ids = {str(item.get("id", "")) for item in items}
    source_ids = {
        str(ref.get("source_id")): str(item.get("id", ""))
        for item in items
        for ref in item.get("provenance", []) if isinstance(item.get("provenance"), list) and isinstance(ref, dict) and ref.get("source_id")
    }
    elements = []
    relations = []
    for item in items:
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        elements.append({"id": str(item.get("id", "")), "kind": str(item.get("element_type", "")), "name": str(payload.get("name", payload.get("title", ""))), "status": "accepted", "attributes": payload, "provenance": item.get("provenance", []), "producer": item.get("producer", "")})
        raw_relations = payload.get("relations", [])
        for relation in raw_relations if isinstance(raw_relations, list) else []:
            if not isinstance(relation, dict):
                continue
            target_id = str(relation.get("target_id", ""))
            target_id = target_id if target_id in accepted_ids else source_ids.get(target_id, "")
            if not target_id:
                continue
            relations.append({"source_id": str(item.get("id", "")), "predicate": str(relation.get("predicate", "relatedTo")), "target_id": target_id})
    elements.sort(key=lambda item: (item["kind"], item["name"], item["id"]))
    relations.sort(key=lambda item: (item["source_id"], item["predicate"], item["target_id"]))
    return {"elements": elements, "relations": relations, "graph_hash": canonical_hash({"elements": elements, "relations": relations})}


def _replace_by_id(existing: object, additions: list[dict[str, object]]) -> list[dict[str, object]]:
    values = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    by_id = {str(item.get("id", "")): item for item in values}
    by_id.update({str(item.get("id", "")): item for item in additions})
    return list(by_id.values())


def bridge_discovery_to_workbench(state: dict[str, object]) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    graph = build_accepted_graph(result)
    accepted = _accepted_items(result)
    mapped = {"stakeholders": [], "concerns": [], "needs": [], "structured_requirements": [], "scenarios": []}
    for item in accepted:
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        identifier = str(item.get("id", ""))
        kind = str(item.get("element_type", ""))
        common = {"id": identifier, "status": "accepted", "producer": item.get("producer", ""), "provenance": item.get("provenance", [])}
        if kind == "stakeholder":
            mapped["stakeholders"].append({**common, "name": payload.get("name", ""), "category": payload.get("category", ""), "inferred": True})
        elif kind == "concern":
            mapped["concerns"].append({**common, "name": payload.get("name", payload.get("value", ""))})
        elif kind == "need":
            mapped["needs"].append({**common, "name": payload.get("name", payload.get("value", "")), "value": payload.get("value", payload.get("name", "")), "stakeholder_id": payload.get("stakeholder_id", ""), "concern_ids": payload.get("concern_ids", [])})
        elif kind == "requirement":
            mapped["structured_requirements"].append({**common, "source_region_id": payload.get("source_region_id", ""), "statement": payload.get("statement", ""), "subject": payload.get("subject", "system"), "predicate": payload.get("predicate", "shall"), "source_type": payload.get("source_type", "inferred"), "verification_method": payload.get("verification_method", payload.get("verification", "analysis"))})
        elif kind == "operational_scenario":
            mapped["scenarios"].append({**common, "title": payload.get("name", ""), "actors": payload.get("actors", []), "preconditions": payload.get("preconditions", []), "steps": payload.get("steps", []), "expected_outcomes": payload.get("expected_outcomes", [payload.get("expected_outcome", "")]), "faults": payload.get("faults", []), "requirement_ids": payload.get("requirement_ids", [])})
    for key, additions in mapped.items():
        result[key] = _replace_by_id(result.get(key, []), additions)
    result["discovery"]["accepted_graph"] = graph
    result["discovery"]["revision"] = int(result["discovery"].get("revision", 0)) + 1
    for key in ("rflp", "mbse", "baseline", "project"):
        result[key] = None
    return result
