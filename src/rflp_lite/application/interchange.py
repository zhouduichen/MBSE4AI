from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


FORMAT = "sysml-lite/rflp"
VERSION = 1
_LAYERS = {"R", "F", "L", "P"}


def _model(value: object) -> dict[str, list[dict[str, object]]]:
    if not isinstance(value, dict):
        raise ContractViolation("RFLP model must be an object")
    elements = value.get("elements")
    relations = value.get("relations")
    if not isinstance(elements, list) or not isinstance(relations, list):
        raise ContractViolation("RFLP model requires elements and relations arrays")
    normalized_elements: list[dict[str, object]] = []
    element_ids: set[str] = set()
    for item in elements:
        if not isinstance(item, dict):
            raise ContractViolation("RFLP element must be an object")
        required = {"id", "layer", "kind", "name"}
        if not required.issubset(item):
            raise ContractViolation("RFLP element requires id, layer, kind, and name")
        item_id = str(item["id"])
        if not item_id or item_id in element_ids:
            raise ContractViolation("RFLP element IDs must be non-empty and unique")
        if item["layer"] not in _LAYERS:
            raise ContractViolation(f"unsupported RFLP layer: {item['layer']}")
        if not str(item["name"]).strip():
            raise ContractViolation("RFLP element name cannot be empty")
        attributes = item.get("attributes", [])
        if not isinstance(attributes, list):
            raise ContractViolation("RFLP element attributes must be an array")
        element_ids.add(item_id)
        normalized_elements.append(
            {
                "id": item_id,
                "layer": str(item["layer"]),
                "kind": str(item["kind"]),
                "name": str(item["name"]),
                "status": str(item.get("status", "approved")),
                "attributes": attributes,
            }
        )
    normalized_relations: list[dict[str, object]] = []
    relation_ids: set[str] = set()
    for index, item in enumerate(relations, start=1):
        if not isinstance(item, dict):
            raise ContractViolation("RFLP relation must be an object")
        if not {"source_id", "predicate", "target_id"}.issubset(item):
            raise ContractViolation("RFLP relation requires source_id, predicate, and target_id")
        relation_id = str(item.get("id") or f"rel-{canonical_hash((item['source_id'], item['predicate'], item['target_id'], index))[:12]}")
        if relation_id in relation_ids:
            raise ContractViolation("RFLP relation IDs must be unique")
        if item["source_id"] not in element_ids or item["target_id"] not in element_ids:
            raise ContractViolation("RFLP relation points to an unknown element")
        relation_ids.add(relation_id)
        normalized_relations.append(
            {
                "id": relation_id,
                "source_id": str(item["source_id"]),
                "predicate": str(item["predicate"]),
                "target_id": str(item["target_id"]),
            }
        )
    return {"elements": normalized_elements, "relations": normalized_relations}


def validate_rflp_model(value: object) -> dict[str, list[dict[str, object]]]:
    """Validate and normalize the shared RFLP model shape for other bridges."""
    return _model(value)


def export_rflp(model: object) -> dict[str, object]:
    normalized = _model(model)
    return {
        "format": FORMAT,
        "version": VERSION,
        "model": normalized,
        "model_hash": canonical_hash(normalized),
    }


def import_rflp(payload: object) -> dict[str, list[dict[str, object]]]:
    if not isinstance(payload, dict):
        raise ContractViolation("SysML-lite exchange payload must be an object")
    if payload.get("format") != FORMAT or payload.get("version") != VERSION:
        raise ContractViolation("unsupported SysML-lite exchange format or version")
    model = _model(payload.get("model"))
    declared_hash = payload.get("model_hash")
    if declared_hash is not None and declared_hash != canonical_hash(model):
        raise ContractViolation("SysML-lite model_hash does not match model")
    return json.loads(json.dumps(model, ensure_ascii=False))
