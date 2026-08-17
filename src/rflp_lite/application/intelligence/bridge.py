"""Accepted semantic graph and conservative compatibility bridge."""

from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json


def seed_domain_pack_workbench(state: dict[str, object], pack: dict[str, object]) -> dict[str, object]:
    """Keep the established workbench useful even when model enrichment is unavailable."""

    result = json.loads(canonical_json(state))
    regions = result.get("document_regions") or result.get("spans") or []
    source_span_id = str(regions[0].get("id", "")) if isinstance(regions, list) and regions and isinstance(regions[0], dict) else ""
    stakeholders = [item for item in result.get("stakeholders", []) if isinstance(item, dict)]
    concerns = [item for item in result.get("concerns", []) if isinstance(item, dict)]
    needs = [item for item in result.get("needs", []) if isinstance(item, dict)]
    stakeholder_names = {str(item.get("name", "")) for item in stakeholders}
    concern_keys = {(str(item.get("stakeholder_id", "")), str(item.get("name", ""))) for item in concerns}
    need_keys = {(str(item.get("stakeholder_id", "")), str(item.get("statement", ""))) for item in needs}
    for source in pack.get("stakeholders", []) if isinstance(pack.get("stakeholders"), list) else []:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name", "")).strip()
        if not name:
            continue
        stakeholder_id = f"pack-stakeholder-{canonical_hash((pack.get('id'), source.get('id', name)))[:12]}"
        if name not in stakeholder_names:
            stakeholders.append({
                "id": stakeholder_id,
                "name": name,
                "category": str(source.get("category", "other")),
                "category_label": str(source.get("category", "other")),
                "goals": list(source.get("goals", [])) if isinstance(source.get("goals"), list) else [],
                "interactions": list(source.get("interactions", [])) if isinstance(source.get("interactions"), list) else [],
                "producer": "domain-pack",
                "candidate_type": "inferred",
                "status": "accepted",
                "source_span_id": source_span_id,
            })
            stakeholder_names.add(name)
        else:
            stakeholder_id = next((str(item.get("id", "")) for item in stakeholders if item.get("name") == name), stakeholder_id)
        for concern_text in source.get("concerns", []) if isinstance(source.get("concerns"), list) else []:
            concern_name = str(concern_text).strip()
            if not concern_name or (stakeholder_id, concern_name) in concern_keys:
                continue
            concern_id = f"pack-concern-{canonical_hash((stakeholder_id, concern_name))[:12]}"
            concerns.append({
                "id": concern_id,
                "name": concern_name,
                "stakeholder_id": stakeholder_id,
                "source_span_id": source_span_id,
                "producer": "domain-pack",
                "candidate_type": "inferred",
                "status": "accepted",
            })
            concern_keys.add((stakeholder_id, concern_name))
            statement = f"{name}需要在系统运行中控制或满足：{concern_name}。"
            if (stakeholder_id, statement) not in need_keys:
                needs.append({
                    "id": f"pack-need-{canonical_hash((stakeholder_id, concern_id))[:12]}",
                    "name": f"{name}的{concern_name}",
                    "statement": statement,
                    "value": statement,
                    "stakeholder_id": stakeholder_id,
                    "concern_id": concern_id,
                    "source_span_id": source_span_id,
                    "producer": "domain-pack",
                    "candidate_type": "inferred",
                    "status": "accepted",
                })
                need_keys.add((stakeholder_id, statement))
    result["stakeholders"] = stakeholders
    result["concerns"] = concerns
    result["needs"] = needs
    return result


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
        common = {"id": identifier, "status": "accepted", "producer": item.get("producer", ""), "provenance": item.get("provenance", []), "candidate_type": "inferred"}
        if kind == "stakeholder":
            mapped["stakeholders"].append({**common, "name": payload.get("name", ""), "category": payload.get("category", ""), "inferred": True})
        elif kind == "concern":
            mapped["concerns"].append({**common, "name": payload.get("name", payload.get("value", "")), "stakeholder_id": payload.get("stakeholder_id", ""), "source_span_id": payload.get("source_span_id", "")})
        elif kind == "need":
            mapped["needs"].append({**common, "name": payload.get("name", payload.get("value", "")), "statement": payload.get("statement", payload.get("value", payload.get("name", ""))), "value": payload.get("value", payload.get("statement", payload.get("name", ""))), "stakeholder_id": payload.get("stakeholder_id", ""), "concern_id": payload.get("concern_id", ""), "concern_ids": payload.get("concern_ids", []), "source_span_id": payload.get("source_span_id", "")})
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


def auto_accept_and_bridge_discovery(
    state: dict[str, object], pack: dict[str, object]
) -> dict[str, object]:
    """Accept generated discovery candidates for the unified quick flow."""

    result = json.loads(canonical_json(state))
    discovery = result.setdefault("discovery", {})
    groups = discovery.get("candidate_sets", []) if isinstance(discovery, dict) else []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or not isinstance(group.get("items"), list):
            continue
        for item in group["items"]:
            if isinstance(item, dict) and item.get("status") == "candidate":
                item["status"] = "accepted"
                item["auto_accepted"] = True

    from rflp_lite.application.intelligence.coverage import evaluate_coverage

    return bridge_discovery_to_workbench(evaluate_coverage(result, pack))
