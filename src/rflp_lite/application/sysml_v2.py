from __future__ import annotations

import json
import re

from rflp_lite.application.interchange import validate_rflp_model
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


PACKAGE = "RFLP_Lite"
_ELEMENT = re.compile(r"^\s*//\s*rflp-element\s+(\{.*\})\s*$")
_RELATION = re.compile(r"^\s*//\s*rflp-relation\s+(\{.*\})\s*$")
_HASH = re.compile(r"^\s*//\s*rflp-model-hash\s+([0-9a-f]{64})\s*$")


def _symbol(identifier: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", identifier)
    return value if value and not value[0].isdigit() else f"e_{value}"


def _element_keyword(layer: str) -> str:
    return {"R": "requirement", "F": "action", "L": "part", "P": "part"}[layer]


def _relation_keyword(predicate: str) -> str:
    return {
        "satisfiedBy": "satisfy",
        "allocatedTo": "allocate",
        "realizedBy": "trace",
    }.get(predicate, "trace")


def export_sysml_v2_text(model: object) -> str:
    normalized = validate_rflp_model(model)
    lines = [f"package {PACKAGE} {{", f"  // rflp-model-hash {canonical_hash(normalized)}"]
    for element in normalized["elements"]:
        lines.append(f"  // rflp-element {canonical_json(element)}")
        lines.append(
            f"  {_element_keyword(str(element['layer']))} def {_symbol(str(element['id']))};"
        )
    for relation in normalized["relations"]:
        lines.append(f"  // rflp-relation {canonical_json(relation)}")
        lines.append(
            "  "
            f"{_relation_keyword(str(relation['predicate']))} "
            f"{_symbol(str(relation['source_id']))} "
            f"{'by' if relation['predicate'] == 'satisfiedBy' else 'to'} "
            f"{_symbol(str(relation['target_id']))};"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def import_sysml_v2_text(text: str) -> dict[str, list[dict[str, object]]]:
    if not isinstance(text, str) or not text.strip():
        raise ContractViolation("SysML v2 text cannot be empty")
    stripped = text.strip()
    if not stripped.startswith(f"package {PACKAGE} {{") or not stripped.endswith("}"):
        raise ContractViolation(f"expected package {PACKAGE}")
    elements: list[dict[str, object]] = []
    relations: list[dict[str, object]] = []
    declared_hash: str | None = None
    for line in text.splitlines():
        match = _HASH.match(line)
        if match:
            declared_hash = match.group(1)
            continue
        match = _ELEMENT.match(line)
        if match:
            try:
                value = json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise ContractViolation("invalid rflp-element metadata") from exc
            if not isinstance(value, dict):
                raise ContractViolation("rflp-element metadata must be an object")
            elements.append(value)
            continue
        match = _RELATION.match(line)
        if match:
            try:
                value = json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise ContractViolation("invalid rflp-relation metadata") from exc
            if not isinstance(value, dict):
                raise ContractViolation("rflp-relation metadata must be an object")
            relations.append(value)

    if not elements:
        raise ContractViolation("SysML v2 subset contains no RFLP elements")
    model = validate_rflp_model({"elements": elements, "relations": relations})
    actual_hash = canonical_hash(model)
    if declared_hash is not None and declared_hash != actual_hash:
        raise ContractViolation("SysML v2 model hash does not match metadata")
    return model
