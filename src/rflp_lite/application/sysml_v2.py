"""Deterministic, dependency-free SysML v2 subset exchange."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json
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
    EntityKind.STATE: "state",
    EntityKind.VERIFICATION_CASE: "verification",
    EntityKind.VALIDATION_CASE: "validation",
}
_SAFE_SYMBOL = re.compile(r"[^A-Za-z0-9_]")
_DECLARATION = re.compile(
    r"^(?P<keyword>part|requirement|action|interface|state|verification|validation)"
    r"\s+(?:def\s+)?(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<body>\{)?\s*;?$"
)
_ATTRIBUTE = re.compile(
    r"^attribute\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*;$"
)
_RELATION = re.compile(
    r"^(?P<keyword>satisfy|allocate|verify|validate)\s+"
    r"(?P<source>[A-Za-z_][A-Za-z0-9_]*)\s+(?:by|to)\s+"
    r"(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*;$"
)
_RELATION_STATEMENT = {
    RelationPredicate.SATISFIED_BY: "satisfy {source} by {target};",
    RelationPredicate.ALLOCATED_TO: "allocate {source} to {target};",
    RelationPredicate.VERIFIED_BY: "verify {source} by {target};",
    RelationPredicate.VALIDATED_BY: "validate {source} by {target};",
}
_PREDICATE_BY_KEYWORD = {
    "satisfy": RelationPredicate.SATISFIED_BY,
    "allocate": RelationPredicate.ALLOCATED_TO,
    "verify": RelationPredicate.VERIFIED_BY,
    "validate": RelationPredicate.VALIDATED_BY,
}
_KIND_BY_KEYWORD = {
    "requirement": EntityKind.REQUIREMENT,
    "action": EntityKind.FUNCTION,
    "interface": EntityKind.INTERFACE,
    "state": EntityKind.STATE,
    "verification": EntityKind.VERIFICATION_CASE,
    "validation": EntityKind.VALIDATION_CASE,
    "part": EntityKind.SYSTEM,
}


def graph_to_sysml(graph: ModelGraph) -> str:
    """Render the graph as readable declarations with round-trip metadata."""

    lines = ["package AI4MBSE_Model {", f"  // @revision: {graph.revision}"]
    for entity in graph.entities:
        data = entity.as_dict()
        lines.append(
            "  // @entity: "
            + json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        keyword = _DECLARATION_KIND.get(entity.kind, "part")
        lines.append(f"  {keyword} def {_symbol(entity.id)} {{")
        for name, value in _entity_attributes(entity):
            lines.append(f"    attribute {name} = {_literal(value)};")
        lines.append("  }")
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
    """Read the declared subset and its optional canonical metadata comments."""

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
    declarations, relation_statements = _parse_declarations(lines[1:-1])
    entities, symbols, max_entity_revision = _read_entities(
        raw_entities, declarations, revision
    )
    relations = _read_relations(
        raw_relations, relation_statements, symbols
    )
    graph = ModelGraph(project_id, tuple(sorted(entities, key=lambda item: item.id)), tuple(sorted(relations, key=lambda item: item.id)), max(revision, max_entity_revision))
    for relation in graph.relations:
        graph.validate_relation(relation)
    return graph


def _entity_attributes(entity: Entity):
    meta = entity.meta
    return (
        ("id", meta.id),
        ("kind", meta.kind.value),
        ("name", meta.name),
        ("status", meta.status.value),
        ("producer", meta.producer.value),
        ("confidence", meta.confidence),
        ("source_ids", list(meta.source_ids)),
        ("evidence_ids", list(meta.evidence_ids)),
        ("lifecycle_ids", list(meta.lifecycle_ids)),
        ("created_revision", meta.created_revision),
        ("updated_revision", meta.updated_revision),
        ("payload_json", canonical_json(entity.payload)),
    )


def _literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_declarations(lines):
    declarations = []
    relation_statements = []
    current = None
    for line in lines:
        if current is not None:
            if line == "}":
                declarations.append(current)
                current = None
                continue
            attribute = _ATTRIBUTE.match(line)
            if attribute:
                current["attributes"][attribute.group("name")] = attribute.group("value")
            continue
        declaration = _DECLARATION.match(line)
        if declaration:
            current = {
                "keyword": declaration.group("keyword"),
                "symbol": declaration.group("symbol"),
                "attributes": {},
            }
            if not declaration.group("body"):
                declarations.append(current)
                current = None
            continue
        relation = _RELATION.match(line)
        if relation:
            relation_statements.append((
                relation.group("keyword"),
                relation.group("source"),
                relation.group("target"),
            ))
    if current is not None:
        raise ContractViolation("SysML declaration is missing closing brace")
    return declarations, relation_statements


def _read_entities(raw_entities, declarations, revision):
    raw_by_id = {}
    for raw in raw_entities:
        entity_id = _required_string(raw, "id")
        if entity_id in raw_by_id:
            raise ContractViolation(f"duplicate SysML entity id: {entity_id}")
        raw_by_id[entity_id] = dict(raw)
    records = []
    symbols = {}
    used_ids = set()
    declarations_by_symbol = {item["symbol"]: item for item in declarations}
    for entity_id, raw in raw_by_id.items():
        declaration = declarations_by_symbol.get(_symbol(entity_id))
        record = _merge_declaration(raw, declaration)
        records.append(record)
        symbols[_symbol(entity_id)] = _required_string(record, "id")
    for declaration in declarations:
        if declaration["symbol"] in symbols:
            continue
        record = _merge_declaration({}, declaration)
        entity_id = _required_string(record, "id")
        if entity_id in used_ids or entity_id in raw_by_id:
            raise ContractViolation(f"duplicate SysML entity id: {entity_id}")
        records.append(record)
        symbols[declaration["symbol"]] = entity_id
        used_ids.add(entity_id)
    entities = []
    entity_ids = set()
    max_entity_revision = 0
    for raw in records:
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
    return entities, symbols, max_entity_revision


def _merge_declaration(raw, declaration):
    record = dict(raw)
    if declaration is None:
        return record
    attributes = declaration["attributes"]
    for name, literal in attributes.items():
        value = _attribute_value(name, literal)
        field = "payload" if name == "payload_json" else name
        record[field] = value
    if not record.get("id"):
        record["id"] = declaration["symbol"]
    if not record.get("kind"):
        record["kind"] = _KIND_BY_KEYWORD[declaration["keyword"]].value
    if not record.get("name"):
        record["name"] = declaration["symbol"]
    return record


def _attribute_value(name: str, literal: str):
    try:
        value = json.loads(literal)
        if name == "payload_json" and isinstance(value, str):
            return json.loads(value)
        return value
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"SysML attribute is not valid JSON: {name}") from exc


def _read_relations(raw_relations, statements, symbols):
    relations = []
    relation_ids = set()
    statement_index = 0
    core_keywords = set(_PREDICATE_BY_KEYWORD)
    for raw in raw_relations:
        relation_id = _required_string(raw, "id")
        if relation_id in relation_ids:
            raise ContractViolation(f"duplicate SysML relation id: {relation_id}")
        relation_ids.add(relation_id)
        try:
            predicate = RelationPredicate(_required_string(raw, "predicate"))
        except ValueError as exc:
            raise ContractViolation(f"invalid SysML relation predicate: {relation_id}") from exc
        record = dict(raw)
        if predicate in _PREDICATE_BY_KEYWORD.values() and statement_index < len(statements):
            keyword, source, target = statements[statement_index]
            if keyword in core_keywords:
                record["source_id"] = _resolve_symbol(source, symbols)
                record["target_id"] = _resolve_symbol(target, symbols)
                record["predicate"] = _PREDICATE_BY_KEYWORD[keyword].value
                statement_index += 1
        relations.append(_relation(record, relation_id))
    while statement_index < len(statements):
        keyword, source, target = statements[statement_index]
        predicate = _PREDICATE_BY_KEYWORD[keyword]
        source_id = _resolve_symbol(source, symbols)
        target_id = _resolve_symbol(target, symbols)
        identity = (source_id, predicate.value, target_id)
        relation_id = f"rel-{canonical_hash(identity)[:16]}"
        relations.append(Relation(relation_id, source_id, predicate, target_id))
        statement_index += 1
    return relations


def _relation(raw, relation_id):
    return Relation(
        relation_id,
        _required_string(raw, "source_id"),
        RelationPredicate(_required_string(raw, "predicate")),
        _required_string(raw, "target_id"),
        _strings(raw.get("evidence_ids")),
    )


def _resolve_symbol(value: str, symbols):
    return symbols.get(value, value)


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
