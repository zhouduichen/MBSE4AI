"""Deterministic, dependency-free SysML v2 subset exchange."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityMeta, EntityStatus, Producer
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


_DECLARATION_KIND: dict[EntityKind, str] = {
    EntityKind.SYSTEM: "part",
    EntityKind.LOGICAL_COMPONENT: "part",
    EntityKind.PHYSICAL_BLOCK: "part",
    EntityKind.REQUIREMENT: "requirement",
    EntityKind.FUNCTION: "action",
    EntityKind.FUNCTIONAL_FLOW: "interface",
    EntityKind.INTERFACE: "interface",
    EntityKind.VERIFICATION_CASE: "verification",
    EntityKind.VALIDATION_CASE: "validation",
}
_SAFE_SYMBOL = re.compile(r"[^A-Za-z0-9_]")
_RELATION_STATEMENT = {
    RelationPredicate.SATISFIED_BY: "satisfy {source} by {target};",
    RelationPredicate.ALLOCATED_TO: "allocate {source} to {target};",
    RelationPredicate.VERIFIED_BY: "verify {source} by {target};",
    RelationPredicate.VALIDATED_BY: "validate {source} by {target};",
}


def graph_to_sysml(graph: ModelGraph) -> str:
    """Render the graph as readable subset declarations with round-trip data."""

    lines = ["package AI4MBSE_Model {", f"  // @revision: {graph.revision}"]
    for entity in graph.entities:
        data = entity.as_dict()
        lines.append(
            "  // @entity: "
            + json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        keyword = _DECLARATION_KIND.get(entity.kind, "part")
        lines.append(f"  {keyword} def {_symbol(entity.id)};")
    for relation in graph.relations:
        data = {
            "id": relation.id,
            "source_id": relation.source_id,
            "predicate": relation.predicate.value,
            "target_id": relation.target_id,
            "evidence_ids": list(relation.evidence_ids),
        }
        statement = _RELATION_STATEMENT.get(relation.predicate)
        if statement:
            lines.append(statement.format(source=_symbol(relation.source_id), target=_symbol(relation.target_id)))
        lines.append(
            "  // @relation: "
            + json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def sysml_to_graph(text: str, project_id: str) -> ModelGraph:
    """Read the deterministic subset emitted by graph_to_sysml."""

    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if len(lines) < 2 or lines[0] != "package AI4MBSE_Model {" or lines[-1] != "}":
        raise ContractViolation("SysML text must contain package AI4MBSE_Model")
    raw_entities: list[Mapping[str, object]] = []
    raw_relations: list[Mapping[str, object]] = []
    revision = 0
    for line in lines[1:-1]:
        if line.startswith("// @revision:"):
            try:
                revision = int(line.split(":", 1)[1].strip())
            except ValueError as exc:
                raise ContractViolation("SysML revision is invalid") from exc
        elif line.startswith("// @entity:"):
            raw_entities.append(_json_record(line, "entity"))
        elif line.startswith("// @relation:"):
            raw_relations.append(_json_record(line, "relation"))

    entities: list[Entity] = []
    entity_ids: set[str] = set()
    max_entity_revision = 0
    for raw in raw_entities:
        entity_id = _required_string(raw, "id")
        if entity_id in entity_ids:
            raise ContractViolation(f"duplicate SysML entity id: {entity_id}")
        entity_ids.add(entity_id)
        try:
            kind = EntityKind(_required_string(raw, "kind"))
            status = EntityStatus(str(raw.get("status", EntityStatus.CANDIDATE.value)))
            producer = Producer(str(raw.get("producer", Producer.RULE.value)))
        except ValueError as exc:
            raise ContractViolation(f"invalid SysML entity enum: {entity_id}") from exc
        name = _required_string(raw, "name")
        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ContractViolation(f"SysML entity payload must be an object: {entity_id}")
        confidence = raw.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as exc:
                raise ContractViolation(f"SysML entity confidence is invalid: {entity_id}") from exc
        created_revision = _nonnegative_int(raw.get("created_revision", revision), "created_revision", entity_id)
        updated_revision = _nonnegative_int(raw.get("updated_revision", revision), "updated_revision", entity_id)
        max_entity_revision = max(max_entity_revision, created_revision, updated_revision)
        meta = EntityMeta(
            entity_id,
            kind,
            name,
            status,
            producer,
            confidence,
            _strings(raw.get("source_ids")),
            _strings(raw.get("evidence_ids")),
            _strings(raw.get("lifecycle_ids")),
            created_revision,
            updated_revision,
        )
        entities.append(Entity(meta, dict(payload)))

    relations: list[Relation] = []
    relation_ids: set[str] = set()
    for raw in raw_relations:
        relation_id = _required_string(raw, "id")
        if relation_id in relation_ids:
            raise ContractViolation(f"duplicate SysML relation id: {relation_id}")
        relation_ids.add(relation_id)
        try:
            predicate = RelationPredicate(_required_string(raw, "predicate"))
        except ValueError as exc:
            raise ContractViolation(f"invalid SysML relation predicate: {relation_id}") from exc
        relation = Relation(
            relation_id,
            _required_string(raw, "source_id"),
            predicate,
            _required_string(raw, "target_id"),
            _strings(raw.get("evidence_ids")),
        )
        relations.append(relation)
    graph = ModelGraph(project_id, tuple(sorted(entities, key=lambda item: item.id)), tuple(sorted(relations, key=lambda item: item.id)), max(revision, max_entity_revision))
    for relation in graph.relations:
        graph.validate_relation(relation)
    return graph


def graph_sysml(graph: ModelGraph) -> str:
    """Backward-compatible export name used by the existing Web API."""

    return graph_to_sysml(graph)


def _symbol(value: str) -> str:
    symbol = _SAFE_SYMBOL.sub("_", str(value))
    if not symbol or symbol[0].isdigit():
        symbol = f"e_{symbol}"
    return symbol


def _json_record(line: str, kind: str) -> Mapping[str, object]:
    marker = f"// @{kind}:"
    try:
        payload = json.loads(line[len(marker):].strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"SysML {kind} metadata is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ContractViolation(f"SysML {kind} metadata must be an object")
    return payload


def _required_string(raw: Mapping[str, object], key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ContractViolation(f"SysML metadata field is required: {key}")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ContractViolation("SysML metadata list field must be an array")
    return tuple(str(item) for item in value)


def _nonnegative_int(value: object, field: str, entity_id: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"SysML {field} is invalid: {entity_id}") from exc
    if result < 0:
        raise ContractViolation(f"SysML {field} cannot be negative: {entity_id}")
    return result
