from __future__ import annotations

import re
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Claim, ModelElement, Relation


_KNOWN_RELATION_PREDICATES = frozenset(
    {
        "satisfiedBy",
        "allocatedTo",
        "realizedBy",
        "interfacesWith",
        "flowsTo",
        "verifiedBy",
        "derivedFrom",
        "refines",
        "exchanges",
    }
)


def _identifier(prefix: str, *parts: object) -> str:
    return f"{prefix}-{canonical_hash(parts)[:12]}"


def _attributes(payload: Mapping[str, object], excluded: set[str]) -> tuple[tuple[str, object], ...]:
    return tuple(
        sorted(
            (
                (str(key), value)
                for key, value in payload.items()
                if str(key) not in excluded and value not in (None, "", [], {})
            ),
            key=lambda item: item[0],
        )
    )


def _attribute_map(element: ModelElement) -> dict[str, object]:
    return {str(key): value for key, value in element.attributes}


def _requirement_ids(element: ModelElement) -> set[str]:
    attributes = _attribute_map(element)
    values = attributes.get("source_requirement_ids", attributes.get("requirement_ids", ()))
    if isinstance(values, str):
        return {values}
    return {str(value) for value in values if str(value)} if isinstance(values, (list, tuple)) else set()


def _architecture_nodes(
    architecture: dict[str, object],
) -> tuple[list[ModelElement], dict[str, ModelElement], list[tuple[dict[str, object], ModelElement]]]:
    specifications = (
        ("functions", "F", "function"),
        ("logical_components", "L", "logical-component"),
        ("physical_components", "P", "physical-component"),
        ("interfaces", "L", "interface"),
    )
    elements: list[ModelElement] = []
    raw_to_element: dict[str, ModelElement] = {}
    interfaces: list[tuple[dict[str, object], ModelElement]] = []
    for collection, layer, default_kind in specifications:
        values = architecture.get(collection, ())
        if not isinstance(values, list):
            continue
        for raw in values:
            if not isinstance(raw, dict):
                continue
            raw_id = str(raw.get("id", ""))
            name = str(raw.get("name") or raw.get("title") or "未命名架构元素").strip()
            if not raw_id or not name:
                continue
            element = ModelElement(
                id=_identifier("arch", layer, raw_id, name),
                layer=layer,
                kind=str(raw.get("kind", default_kind)),
                name=name,
                status=(
                    "approved"
                    if str(raw.get("status", "accepted")) == "accepted"
                    else str(raw.get("status", "accepted"))
                ),
                attributes=_attributes(
                    raw,
                    {"id", "layer", "kind", "name", "title", "status"},
                ),
            )
            elements.append(element)
            raw_to_element[raw_id] = element
            if collection == "interfaces":
                interfaces.append((raw, element))
    return elements, raw_to_element, interfaces


def _placeholder(
    layer: str, claim: Claim, role: str, name: str
) -> ModelElement:
    return ModelElement(
        id=_identifier(f"{layer.lower()}-placeholder", claim.id, role),
        layer=layer,
        kind=f"{role}-needs-analysis",
        name=name,
        status="needs-analysis",
        attributes=(
            ("source_requirement_ids", (claim.id,)),
            ("reason", "LLM 未提供足够架构细节"),
        ),
    )


def _is_gap(element: ModelElement) -> bool:
    return element.status == "needs-analysis" or element.kind.endswith("-needs-analysis")


def _legacy_synthesize_rflp(
    claims: tuple[Claim, ...],
) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]:
    """Keep the original direct/CLI synthesis contract for non-LLM callers.

    The web auto-analysis path always passes an explicit architecture object,
    including an empty object when the LLM returned no architecture. That
    path therefore gets explicit ``needs-analysis`` nodes instead of silently
    inventing a domain model. Direct library and CLI callers still need the
    long-standing deterministic graph so project-bridge workflows remain
    backwards compatible.
    """

    requirements: list[ModelElement] = []
    functions: list[ModelElement] = []
    logical: list[ModelElement] = []
    physical_by_name: dict[str, ModelElement] = {}
    relations: list[Relation] = []
    for claim in sorted(claims, key=lambda item: item.id):
        requirement = ModelElement(
            id=_identifier("req", claim.id),
            layer="R",
            kind="requirement",
            name=claim.object.rstrip(".。"),
            attributes=(("claim_id", claim.id), ("source_requirement_ids", (claim.id,))),
        )
        function = ModelElement(
            id=_identifier("fn", claim.id),
            layer="F",
            kind="function",
            name=claim.object.rstrip(".。"),
            attributes=(
                ("input", "request context"),
                ("output", "validated result"),
                ("precondition", "request is authorized"),
                ("postcondition", claim.object.rstrip(".。")),
                ("failure_mode", "validation or execution failure"),
                ("source_requirement_ids", (claim.id,)),
            ),
        )
        subject = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", claim.subject).strip()
        action = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", claim.object).strip()
        logical_element = ModelElement(
            id=_identifier("logical", claim.id),
            layer="L",
            kind="logical-component",
            name=f"{subject or 'System'} · {action[:24]} Service",
            attributes=(("source_requirement_ids", (claim.id,)),),
        )
        physical_name = "Generic System Implementation"
        physical = physical_by_name.setdefault(
            physical_name,
            ModelElement(
                id=_identifier("physical", physical_name),
                layer="P",
                kind="physical-component",
                name=physical_name,
                attributes=(("source_requirement_ids", (claim.id,)),),
            ),
        )
        requirements.append(requirement)
        functions.append(function)
        logical.append(logical_element)
        for source, predicate, target in (
            (requirement, "satisfiedBy", function),
            (function, "allocatedTo", logical_element),
            (logical_element, "realizedBy", physical),
        ):
            relations.append(
                Relation(
                    _identifier("rel", source.id, predicate, target.id),
                    source.id,
                    predicate,
                    target.id,
                )
            )
    elements = tuple(
        sorted(
            requirements + functions + logical + list(physical_by_name.values()),
            key=lambda item: ("RFLP".index(item.layer), item.name, item.id),
        )
    )
    return elements, tuple(sorted(relations, key=lambda item: item.id))


def synthesize_rflp(
    claims: tuple[Claim, ...],
    architecture: dict[str, object] | None = None,
) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]:
    """Build a deterministic RFLP graph, enriching it with project LLM architecture."""

    if not claims:
        raise InvariantViolation("at least one accepted claim is required")
    if architecture is None:
        return _legacy_synthesize_rflp(claims)
    architecture = architecture if isinstance(architecture, dict) else {}
    requirements: list[ModelElement] = []
    functions: list[ModelElement] = []
    logical: list[ModelElement] = []
    physical: list[ModelElement] = []
    relations: list[Relation] = []
    relation_keys: set[tuple[str, str, str]] = set()
    architecture_elements, raw_to_element, interface_specs = _architecture_nodes(architecture)
    functions.extend(item for item in architecture_elements if item.layer == "F")
    logical.extend(
        item for item in architecture_elements
        if item.layer == "L" and item.kind != "interface"
    )
    physical.extend(item for item in architecture_elements if item.layer == "P")
    interfaces = [item for item in architecture_elements if item.kind == "interface"]

    def add_relation(source: ModelElement, predicate: str, target: ModelElement) -> None:
        key = (source.id, predicate, target.id)
        if key in relation_keys:
            return
        relation_keys.add(key)
        relations.append(Relation(_identifier("rel", *key), source.id, predicate, target.id))

    for raw, interface in interface_specs:
        source = raw_to_element.get(str(raw.get("source_id", "")))
        target = raw_to_element.get(str(raw.get("target_id", "")))
        if source is not None:
            add_relation(source, "exchanges", interface)
        if target is not None:
            add_relation(interface, "exchanges", target)

    for raw in architecture.get("relations", ()) if isinstance(architecture.get("relations"), list) else ():
        if not isinstance(raw, dict):
            continue
        source = raw_to_element.get(str(raw.get("source_id", "")))
        target = raw_to_element.get(str(raw.get("target_id", "")))
        predicate = str(raw.get("predicate", ""))
        if source is not None and target is not None and predicate in _KNOWN_RELATION_PREDICATES:
            add_relation(source, predicate, target)

    for claim in sorted(claims, key=lambda item: item.id):
        requirement = ModelElement(
            id=_identifier("req", claim.id),
            layer="R",
            kind="requirement",
            name=claim.object.rstrip(".。"),
            attributes=(
                ("claim_id", claim.id),
                ("source_requirement_ids", (claim.id,)),
            ),
        )
        requirements.append(requirement)

        claim_functions = [item for item in functions if claim.id in _requirement_ids(item)]
        if not claim_functions:
            claim_functions = [
                _placeholder("F", claim, "function", f"待 LLM 分析的功能：{claim.object[:24]}")
            ]
            functions.extend(claim_functions)
        claim_logical = [item for item in logical if claim.id in _requirement_ids(item)]
        if not claim_logical:
            claim_logical = [
                _placeholder("L", claim, "logical-component", f"待 LLM 分析的逻辑组件：{claim.object[:20]}")
            ]
            logical.extend(claim_logical)
        claim_physical = [item for item in physical if claim.id in _requirement_ids(item)]
        if not claim_physical:
            claim_physical = [
                _placeholder("P", claim, "physical-component", f"待 LLM 分析的物理实现：{claim.object[:20]}")
            ]
            physical.extend(claim_physical)

        for function in claim_functions:
            if not _is_gap(function):
                add_relation(requirement, "satisfiedBy", function)
            for component in claim_logical:
                if not _is_gap(function) and not _is_gap(component):
                    add_relation(function, "allocatedTo", component)
        for component in claim_logical:
            for implementation in claim_physical:
                if not _is_gap(component) and not _is_gap(implementation):
                    add_relation(component, "realizedBy", implementation)

    elements = tuple(
        sorted(
            requirements + functions + logical + physical + interfaces,
            key=lambda item: ("RFLP".index(item.layer), item.name, item.id),
        )
    )
    return elements, tuple(sorted(relations, key=lambda item: item.id))
