"""Versioned, layout-free MBSE semantics shared by every diagram view."""

from __future__ import annotations

import json
from collections.abc import Iterable

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.application.use_case_modeling import canonical_flow_identity


MBSE_SEMANTIC_MODEL_VERSION = 2
SEMANTIC_FORMAT = "ai4mbse/mbse-semantic"

SECTION_KEYS = ("operational", "functional", "logical", "physical")
RELATION_KINDS = frozenset(
    {
        "allocatedTo",
        "contains",
        "derivedFrom",
        "flowsTo",
        "interfacesWith",
        "participatesIn",
        "performedBy",
        "realizedBy",
        "refines",
        "satisfiedBy",
        "transitionsTo",
        "triggers",
        "verifiedBy",
        "relatedTo",
    }
)

FORMAL_RELATION_ENDPOINTS = {
    "satisfiedBy": ({"requirement"}, {"function"}),
    "allocatedTo": ({"function"}, {"logical_component"}),
    "realizedBy": ({"logical_component"}, {"physical_block"}),
    "interfacesWith": ({"stakeholder", "logical_component", "physical_block", "interface"}, {"logical_component", "physical_block", "interface"}),
    "flowsTo": ({"interface", "logical_component", "physical_block"}, {"interface", "logical_component", "physical_block"}),
    "verifiedBy": ({"requirement"}, {"evidence", "test", "simulation"}),
    "derivedFrom": ({"source_region", "concern", "need"}, {"requirement"}),
    "refines": ({"concern", "need", "requirement"}, {"requirement", "technical_requirement"}),
}


def _clone(value: object) -> object:
    return json.loads(canonical_json(value))


def _list(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(raw: object, *keys: str, fallback: str = "") -> str:
    if not isinstance(raw, dict):
        return fallback
    for key in keys:
        value = str(raw.get(key, "")).strip()
        if value:
            return value
    return fallback


def _source(raw: object, state: dict[str, object]) -> dict[str, object]:
    value = raw if isinstance(raw, dict) else {}
    source_ids = []
    for key in ("source_span_id", "source_region_id", "source_id"):
        item = str(value.get(key, "")).strip()
        if item:
            source_ids.append(item)
    source_ids.extend(
        str(item).strip()
        for key in ("source_span_ids", "source_region_ids")
        for item in value.get(key, ())
        if str(item).strip()
    )
    return {
        "span_ids": sorted(set(source_ids)),
        "input_hash": str(
            (state.get("project_scope") or {}).get("input_hash", "")
            if isinstance(state.get("project_scope"), dict)
            else ""
        ),
    }


def _entity(
    state: dict[str, object],
    entity_id: str,
    kind: str,
    name: str,
    raw: object = None,
    *,
    status: str = "accepted",
    producer: str | None = None,
    needs_analysis: bool = False,
    **attributes: object,
) -> dict[str, object]:
    value = raw if isinstance(raw, dict) else {}
    return {
        "id": entity_id,
        "kind": kind,
        "name": name or entity_id,
        "status": status,
        "producer": producer or str(value.get("producer", "rule")),
        "source": _source(value, state),
        "needs_analysis": needs_analysis,
        "attributes": {
            key: _clone(item)
            for key, item in {**value, **attributes}.items()
            if key not in {"id", "name", "status", "producer", "source"}
        },
    }


def _relation(
    source_id: str,
    kind: str,
    target_id: str,
    *,
    producer: str = "rule",
    confidence: float = 1.0,
    evidence: Iterable[str] = (),
) -> dict[str, object]:
    return {
        "id": f"rel-{canonical_hash((source_id, kind, target_id))[:16]}",
        "source_id": source_id,
        "kind": kind,
        "target_id": target_id,
        "producer": producer,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "evidence": sorted(set(str(item) for item in evidence if str(item))),
    }


def _section_entities(section: object) -> Iterable[dict[str, object]]:
    if isinstance(section, list):
        return tuple(
            item for item in section if isinstance(item, dict) and item.get("id")
        )
    if not isinstance(section, dict):
        return ()
    values: list[dict[str, object]] = []
    for key, raw_items in section.items():
        if key == "relations":
            continue
        if isinstance(raw_items, list):
            values.extend(item for item in raw_items if isinstance(item, dict) and item.get("id"))
    return values


def mbse_entity_index(model: dict[str, object]) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    sections = model.get("sections", {}) if isinstance(model, dict) else {}
    for section in sections.values() if isinstance(sections, dict) else ():
        for item in _section_entities(section):
            item_id = str(item["id"])
            if item_id in index:
                raise ContractViolation(f"MBSE semantic entity id duplicated: {item_id}")
            index[item_id] = item
    return index


def validate_mbse_semantic_model(model: object) -> tuple[str, ...]:
    """Return deterministic validation issues for a semantic model."""

    issues: list[str] = []
    if not isinstance(model, dict):
        return ("model must be an object",)
    if model.get("format") != SEMANTIC_FORMAT:
        issues.append("unsupported semantic format")
    if model.get("version") != MBSE_SEMANTIC_MODEL_VERSION:
        issues.append("unsupported semantic model version")
    sections = model.get("sections")
    if not isinstance(sections, dict):
        return tuple(issues + ["sections must be an object"])
    for key in SECTION_KEYS:
        if not isinstance(sections.get(key), dict):
            issues.append(f"missing section: {key}")
    try:
        index = mbse_entity_index(model)
    except ContractViolation as exc:
        issues.append(str(exc))
        index = {}
    relation_ids: set[str] = set()
    relations = model.get("relations")
    if not isinstance(relations, list):
        issues.append("relations must be an array")
        relations = []
    for relation in relations:
        if not isinstance(relation, dict):
            issues.append("relation must be an object")
            continue
        relation_id = str(relation.get("id", ""))
        if not relation_id:
            issues.append("relation requires id")
        elif relation_id in relation_ids:
            issues.append(f"relation id duplicated: {relation_id}")
        relation_ids.add(relation_id)
        kind = str(relation.get("kind", ""))
        if kind not in RELATION_KINDS:
            issues.append(f"unsupported relation kind: {kind}")
        source_id = str(relation.get("source_id", ""))
        target_id = str(relation.get("target_id", ""))
        if source_id not in index or target_id not in index:
            issues.append(f"relation endpoint not found: {source_id} -> {target_id}")
        elif kind in FORMAL_RELATION_ENDPOINTS:
            source_kind = str(index[source_id].get("kind", ""))
            target_kind = str(index[target_id].get("kind", ""))
            allowed_source, allowed_target = FORMAL_RELATION_ENDPOINTS[kind]
            if source_kind not in allowed_source or target_kind not in allowed_target:
                issues.append(
                    f"relation endpoint type invalid: {kind} ({source_kind} -> {target_kind})"
                )
    return tuple(issues)


def _requirement_items(state: dict[str, object]) -> list[dict[str, object]]:
    values = [
        item
        for item in _list(state.get("structured_requirements"))
        if str(item.get("status", "accepted")) == "accepted"
    ]
    if values:
        return values
    return [
        {
            "id": str(item.get("id", "")),
            "statement": str(item.get("object", item.get("statement", ""))),
            "subject": item.get("subject", "系统"),
            "verification_method": item.get("verification_method", "analysis"),
            "status": item.get("status", "accepted"),
            "producer": item.get("producer", "rule"),
            "source_span_id": item.get("span_id", ""),
        }
        for item in _list(state.get("claims"))
        if str(item.get("status", "")) == "accepted"
    ]


def _has_technical_evidence(item: dict[str, object]) -> bool:
    verification = str(item.get("verification_method", item.get("verification", ""))).strip().casefold()
    return bool(
        verification
        and verification not in {"analysis", "分析", ""}
        or item.get("technical_parameters")
        or item.get("parameters")
        or item.get("constraints")
        or item.get("domain_rule")
        or item.get("domain_rules")
    )


def build_legacy_mbse_semantic_model(
    analysis: dict[str, object],
    revision: object = None,
    provenance: object = None,
) -> dict[str, object]:
    """Build complete operational/functional/logical/physical semantics.

    The input is the project workbench, not an LLM-specific response.  This
    keeps manual edits, rule-derived content and LLM content on one contract.
    """

    state = analysis
    requirements = _requirement_items(state)
    if not requirements:
        raise ContractViolation("请先接受至少一条结构化需求")
    workspace = str((state.get("project_scope") or {}).get("workspace", "")) if isinstance(state.get("project_scope"), dict) else ""
    project_name = _text(state.get("system_context"), "name", fallback="当前项目")
    sections: dict[str, dict[str, object]] = {
        "operational": {
            "environment": [],
            "sources": [],
            "stakeholders": [],
            "stakeholder_hierarchy": [],
            "concerns": [],
            "needs": [],
            "use_cases": [],
            "lifecycle": [],
            "scenarios": [],
        },
        "functional": {"requirements": [], "functions": [], "flows": [], "scenarios": [], "gaps": []},
        "logical": {"components": [], "flows": [], "interfaces": [], "gaps": []},
        "physical": {"components": [], "flows": [], "interfaces": [], "allocations": [], "gaps": []},
        "technical_requirements": [],
    }
    relations: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []

    environment_id = f"environment-{canonical_hash((workspace, project_name))[:12]}"
    environment = _entity(
        state,
        environment_id,
        "environment",
        project_name,
        state.get("system_context"),
        producer="rule",
        description=_text(state.get("system_context"), "mission", fallback="项目运行环境与边界"),
    )
    sections["operational"]["environment"] = [environment]

    for raw_source in _list(state.get("document_regions")):
        source_id = str(raw_source.get("id", ""))
        if source_id:
            sections["operational"]["sources"].append(
                _entity(
                    state,
                    source_id,
                    "source_region",
                    _text(raw_source, "text", fallback=source_id)[:120],
                    raw_source,
                    producer="source",
                )
            )

    stakeholder_items = _list(state.get("stakeholders"))
    stakeholder_ids: list[str] = []
    for item in stakeholder_items:
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        stakeholder_ids.append(item_id)
        sections["operational"]["stakeholders"].append(
            _entity(
                state,
                item_id,
                "stakeholder",
                _text(item, "name", fallback=item_id),
                item,
                status=str(item.get("status", "accepted")),
                goals=item.get("goals", ()),
                interactions=item.get("interactions", ()),
            )
        )
        relations.append(_relation(environment_id, "contains", item_id, producer=str(item.get("producer", "rule"))))
    if not stakeholder_ids:
        subjects = sorted(
            {
                _text(item, "subject", fallback="使用者")
                for item in requirements
            }
        )
        for subject in subjects or ["使用者"]:
            item_id = f"stakeholder-{canonical_hash((workspace, subject))[:12]}"
            stakeholder_ids.append(item_id)
            sections["operational"]["stakeholders"].append(
                _entity(
                    state,
                    item_id,
                    "stakeholder",
                    subject,
                    {"producer": "rule"},
                    needs_analysis=True,
                )
            )
            relations.append(_relation(environment_id, "contains", item_id, producer="rule"))
    sections["operational"]["stakeholder_hierarchy"] = [
        {"parent_id": environment_id, "child_id": item_id, "level": 1}
        for item_id in sorted(stakeholder_ids)
    ]

    concern_ids: list[str] = []
    for item in _list(state.get("concerns")):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        concern_ids.append(item_id)
        sections["operational"]["concerns"].append(
            _entity(state, item_id, "concern", _text(item, "name", fallback=item_id), item)
        )
        stakeholder_id = str(item.get("stakeholder_id", ""))
        if stakeholder_id in stakeholder_ids:
            relations.append(_relation(stakeholder_id, "relatedTo", item_id, producer=str(item.get("producer", "rule"))))

    need_ids: list[str] = []
    for item in _list(state.get("needs")):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        need_ids.append(item_id)
        sections["operational"]["needs"].append(
            _entity(
                state,
                item_id,
                "need",
                _text(item, "name", "statement", fallback=item_id),
                item,
                statement=_text(item, "statement", "name"),
            )
        )
        for source_id in (str(item.get("stakeholder_id", "")), str(item.get("concern_id", ""))):
            if source_id in {*stakeholder_ids, *concern_ids}:
                relations.append(_relation(source_id, "relatedTo", item_id, producer=str(item.get("producer", "rule"))))

    requirement_ids: list[str] = []
    for item in requirements:
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        requirement_ids.append(item_id)
        requirement_entity = _entity(
            state,
            item_id,
            "requirement",
            _text(item, "statement", "object", fallback=item_id),
            item,
            status=str(item.get("status", "accepted")),
            statement=_text(item, "statement", "object"),
            verification_method=_text(item, "verification_method", "verification", fallback="analysis"),
        )
        sections["functional"]["requirements"].append(requirement_entity)
        source_id = _text(item, "source_region_id", "source_span_id")
        if source_id.startswith("span-"):
            source_id = source_id.replace("span-", "region-", 1)
        if source_id:
            relations.append(_relation(source_id, "derivedFrom", item_id, producer=str(item.get("producer", "rule"))))
        need_id = str(item.get("need_id", ""))
        if need_id in need_ids:
            relations.append(_relation(need_id, "refines", item_id, producer=str(item.get("producer", "rule"))))

        if _has_technical_evidence(item):
            technical_id = f"tech-{canonical_hash((item_id, 'technical'))[:12]}"
            sections["technical_requirements"].append(
                _entity(
                    state,
                    technical_id,
                    "technical_requirement",
                    _text(item, "technical_name", fallback=f"技术约束：{requirement_entity['name']}"),
                    item,
                    verification_method=requirement_entity["attributes"].get("verification_method", "analysis"),
                    source_requirement_id=item_id,
                )
            )
            relations.append(_relation(item_id, "refines", technical_id, producer="rule"))

    scenario_items = _list(state.get("scenarios"))
    for index, item in enumerate(scenario_items):
        item_id = str(item.get("id", "")) or f"scenario-{index + 1}"
        flow_identity_id, flow_identity_hash = canonical_flow_identity(
            item.get("interaction_steps") or item.get("steps") or ()
        )
        scenario_payload = {
            **item,
            "canonical_flow_id": str(item.get("canonical_flow_id") or flow_identity_id),
            "canonical_flow_hash": str(item.get("canonical_flow_hash") or flow_identity_hash),
        }
        sections["operational"]["scenarios"].append(
            _entity(
                state,
                item_id,
                "operational_scenario",
                _text(item, "title", "name", fallback=item_id),
                scenario_payload,
                scenario_type=_text(item, "scenario_type", fallback="normal"),
                steps=item.get("steps", ()),
                expected_outcomes=item.get("expected_outcomes", ()),
            )
        )
        for requirement_id in item.get("requirement_ids", ()):
            if str(requirement_id) in requirement_ids:
                relations.append(_relation(item_id, "triggers", str(requirement_id), producer=str(item.get("producer", "rule"))))
        for actor_id in item.get("actor_ids", ()) or item.get("actors", ()):
            if str(actor_id) in stakeholder_ids:
                relations.append(_relation(str(actor_id), "participatesIn", item_id, producer=str(item.get("producer", "rule"))))

    if not scenario_items:
        for requirement_id in requirement_ids:
            scenario_id = f"scenario-{canonical_hash((requirement_id, 'normal'))[:12]}"
            fallback_steps = ["识别任务条件", "执行系统功能", "确认结果"]
            flow_identity_id, flow_identity_hash = canonical_flow_identity(fallback_steps)
            sections["operational"]["scenarios"].append(
                _entity(
                    state,
                    scenario_id,
                    "operational_scenario",
                    f"验证：{requirement_id}",
                    {
                        "producer": "rule",
                        "steps": fallback_steps,
                        "requirement_ids": [requirement_id],
                        "canonical_flow_id": flow_identity_id,
                        "canonical_flow_hash": flow_identity_hash,
                    },
                    needs_analysis=True,
                    scenario_type="normal",
                    steps=["识别任务条件", "执行系统功能", "确认结果"],
                )
            )
            relations.append(_relation(scenario_id, "triggers", requirement_id, producer="rule"))

    architecture = state.get("discovery", {}).get("architecture", {}) if isinstance(state.get("discovery"), dict) else {}
    architecture = architecture if isinstance(architecture, dict) else {}
    function_ids: list[str] = []
    for item in _list(architecture.get("functions")):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        function_ids.append(item_id)
        sections["functional"]["functions"].append(
            _entity(state, item_id, "function", _text(item, "name", fallback=item_id), item, responsibilities=item.get("responsibilities", ()))
        )
        for requirement_id in item.get("requirement_ids", ()):
            if str(requirement_id) in requirement_ids:
                relations.append(_relation(str(requirement_id), "satisfiedBy", item_id, producer=str(item.get("producer", "rule"))))
    covered_requirements = {
        relation["source_id"]
        for relation in relations
        if relation["kind"] == "satisfiedBy"
    }
    for requirement_id in requirement_ids:
        if requirement_id not in covered_requirements:
            sections["functional"]["gaps"].append(
                _entity(
                    state,
                    f"gap-function-{canonical_hash((requirement_id, 'function'))[:12]}",
                    "analysis_gap",
                    "缺失功能实现",
                    {"producer": "rule"},
                    status="needs-analysis",
                    needs_analysis=True,
                    missing_kind="function",
                    requirement_id=requirement_id,
                    reason="No evidence-backed functional realization",
                )
            )

    logical_ids: list[str] = []
    for item in _list(architecture.get("logical_components")):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        logical_ids.append(item_id)
        sections["logical"]["components"].append(
            _entity(state, item_id, "logical_component", _text(item, "name", fallback=item_id), item, responsibilities=item.get("responsibilities", ()))
        )
    if not logical_ids:
        for requirement_id in requirement_ids:
            sections["logical"]["gaps"].append(
                _entity(
                    state,
                    f"gap-logical-{canonical_hash((requirement_id, 'logical'))[:12]}",
                    "analysis_gap",
                    "缺失逻辑组件",
                    {"producer": "rule"},
                    status="needs-analysis",
                    needs_analysis=True,
                    missing_kind="logical_component",
                    requirement_id=requirement_id,
                    reason="No evidence-backed logical realization",
                )
            )
    physical_ids: list[str] = []
    for item in _list(architecture.get("physical_components")):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        physical_ids.append(item_id)
        sections["physical"]["components"].append(
            _entity(state, item_id, "physical_block", _text(item, "name", fallback=item_id), item)
        )
    if not physical_ids:
        for requirement_id in requirement_ids:
            sections["physical"]["gaps"].append(
                _entity(
                    state,
                    f"gap-physical-{canonical_hash((requirement_id, 'physical'))[:12]}",
                    "analysis_gap",
                    "缺失物理实现",
                    {"producer": "rule"},
                    status="needs-analysis",
                    needs_analysis=True,
                    missing_kind="physical_component",
                    requirement_id=requirement_id,
                    reason="No evidence-backed physical realization",
                )
            )

    explicit_allocations = _list(architecture.get("allocations"))
    for allocation in explicit_allocations:
        source_id = str(allocation.get("source_id", allocation.get("function_id", "")))
        target_id = str(allocation.get("target_id", allocation.get("logical_id", "")))
        if source_id in function_ids and target_id in logical_ids:
            relations.append(_relation(source_id, "allocatedTo", target_id, producer=str(allocation.get("producer", "rule"))))
    explicit_realizations = _list(architecture.get("realizations"))
    for realization in explicit_realizations:
        source_id = str(realization.get("source_id", realization.get("logical_id", "")))
        target_id = str(realization.get("target_id", realization.get("physical_id", "")))
        if source_id in logical_ids and target_id in physical_ids:
            relations.append(_relation(source_id, "realizedBy", target_id, producer=str(realization.get("producer", "rule"))))

    allocated_functions = {
        relation["source_id"]
        for relation in relations
        if relation["kind"] == "allocatedTo"
    }
    realized_logical = {
        relation["source_id"]
        for relation in relations
        if relation["kind"] == "realizedBy"
    }
    for function_id in function_ids:
        if function_id not in allocated_functions:
            sections["logical"]["gaps"].append(
                _entity(
                    state,
                    f"gap-allocation-{canonical_hash((function_id, 'allocation'))[:12]}",
                    "analysis_gap",
                    "缺失功能分配",
                    {"producer": "rule"},
                    status="needs-analysis",
                    needs_analysis=True,
                    missing_kind="allocation",
                    source_id=function_id,
                    reason="No evidence-backed function allocation",
                )
            )
    for logical_id in logical_ids:
        if logical_id not in realized_logical:
            sections["physical"]["gaps"].append(
                _entity(
                    state,
                    f"gap-realization-{canonical_hash((logical_id, 'realization'))[:12]}",
                    "analysis_gap",
                    "缺失逻辑到物理实现",
                    {"producer": "rule"},
                    status="needs-analysis",
                    needs_analysis=True,
                    missing_kind="realization",
                    source_id=logical_id,
                    reason="No evidence-backed logical realization",
                )
            )

    interface_ids: list[str] = []
    for item in _list(architecture.get("interfaces")):
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        interface_ids.append(item_id)
        sections["logical"]["interfaces"].append(
            _entity(state, item_id, "interface", _text(item, "name", fallback=item_id), item)
        )
        source_id = str(item.get("source_id", ""))
        target_id = str(item.get("target_id", ""))
        if source_id and target_id:
            relations.append(_relation(source_id, "interfacesWith", target_id, producer=str(item.get("producer", "rule"))))

    lifecycle = state.get("discovery", {}).get("lifecycle", ()) if isinstance(state.get("discovery"), dict) else ()
    lifecycle = lifecycle if isinstance(lifecycle, list) else []
    if not lifecycle:
        lifecycle = [
            {"id": "lifecycle-definition", "name": "定义与验证"},
            {"id": "lifecycle-operation", "name": "运行与维护"},
            {"id": "lifecycle-retirement", "name": "退役与归档"},
        ]
    lifecycle_ids: list[str] = []
    for index, item in enumerate(_list(lifecycle)):
        item_id = str(item.get("id", "")) or f"lifecycle-{index + 1}"
        lifecycle_ids.append(item_id)
        sections["operational"]["lifecycle"].append(
            _entity(state, item_id, "lifecycle_phase", _text(item, "name", "label", fallback=item_id), item)
        )
        if index:
            relations.append(_relation(lifecycle_ids[index - 1], "transitionsTo", item_id, producer="rule"))

    all_sections = {**sections}
    for raw in _list(architecture.get("relations")):
        source_id = str(raw.get("source_id", ""))
        predicate = str(raw.get("predicate", ""))
        target_id = str(raw.get("target_id", ""))
        if predicate not in RELATION_KINDS:
            diagnostics.append(
                {
                    "code": "unknown_relation_kind",
                    "severity": "error",
                    "message": f"未知关系类型已拒绝: {predicate}",
                    "source_id": source_id,
                    "target_id": target_id,
                }
            )
            continue
        if source_id and target_id:
            relations.append(
                _relation(
                    source_id,
                    predicate,
                    target_id,
                    producer=str(raw.get("producer", "llm")),
                    confidence=float(raw.get("confidence", 1.0) or 1.0),
                    evidence=raw.get("source_region_ids", ()),
                )
            )

    allocated_functions = {
        relation["source_id"]
        for relation in relations
        if relation["kind"] == "allocatedTo"
    }
    realized_logical = {
        relation["source_id"]
        for relation in relations
        if relation["kind"] == "realizedBy"
    }
    sections["logical"]["gaps"] = [
        gap
        for gap in sections["logical"]["gaps"]
        if not (
            gap.get("attributes", {}).get("missing_kind") == "allocation"
            and gap.get("attributes", {}).get("source_id") in allocated_functions
        )
    ]
    sections["physical"]["gaps"] = [
        gap
        for gap in sections["physical"]["gaps"]
        if not (
            gap.get("attributes", {}).get("missing_kind") == "realization"
            and gap.get("attributes", {}).get("source_id") in realized_logical
        )
    ]

    model = {
        "format": SEMANTIC_FORMAT,
        "version": MBSE_SEMANTIC_MODEL_VERSION,
        "workspace": workspace,
        "revision": str(revision if revision is not None else state.get("revision", "")),
        "provenance": _clone(provenance if provenance is not None else {"producer": "rule+llm"}),
        "diagnostics": diagnostics,
        "sections": all_sections,
        "relations": sorted(
            {str(item["id"]): item for item in relations}.values(),
            key=lambda item: (str(item["source_id"]), str(item["kind"]), str(item["target_id"])),
        ),
    }
    issues = validate_mbse_semantic_model(model)
    if issues:
        raise ContractViolation(f"MBSE semantic model invalid: {'; '.join(issues[:6])}")
    model["model_hash"] = canonical_hash(model)
    return model


def legacy_mbse_projection(model: dict[str, object]) -> dict[str, object]:
    """Project version-2 semantics to the existing v1 MBSE collections."""

    issues = validate_mbse_semantic_model(model)
    if issues:
        raise ContractViolation(f"MBSE semantic model invalid: {'; '.join(issues[:6])}")
    sections = model["sections"]
    operational = sections["operational"]
    functional = sections["functional"]
    actors = [
        {
            "id": item["id"],
            "name": item["name"],
            "requirement_ids": [],
            "status": item.get("status", "accepted"),
        }
        for item in operational["stakeholders"]
    ]
    lifelines = [{"id": "lifeline-system", "name": "系统", "status": "accepted"}]
    lifelines.extend(
        {"id": f"lifeline-{item['id']}", "name": item["name"], "status": item.get("status", "accepted")}
        for item in operational["stakeholders"]
    )
    use_cases = [
        {
            "id": item["id"],
            "name": item["name"],
            "actor_ids": [relation["source_id"] for relation in model["relations"] if relation["kind"] == "participatesIn" and relation["target_id"] == item["id"]],
            "requirement_ids": list(item.get("attributes", {}).get("requirement_ids", ())),
            "preconditions": list(item.get("attributes", {}).get("preconditions", ())),
            "postconditions": list(item.get("attributes", {}).get("expected_outcomes", ())),
            "main_flow": list(item.get("attributes", {}).get("interaction_steps", item.get("attributes", {}).get("steps", ()))),
            "canonical_flow_id": item.get("attributes", {}).get("canonical_flow_id", ""),
            "canonical_flow_hash": item.get("attributes", {}).get("canonical_flow_hash", ""),
            "status": item.get("status", "accepted"),
        }
        for item in operational["scenarios"]
    ]
    activities = [
        {
            "id": f"activity-{item['id']}",
            "name": item["name"],
            "kind": "use_case_flow",
            "steps": list(item.get("attributes", {}).get("interaction_steps", item.get("attributes", {}).get("steps", ()))),
            "canonical_flow_id": item.get("attributes", {}).get("canonical_flow_id", ""),
            "canonical_flow_hash": item.get("attributes", {}).get("canonical_flow_hash", ""),
            "predecessor_ids": [],
            "requirement_ids": list(item.get("attributes", {}).get("requirement_ids", ())),
            "status": item.get("status", "accepted"),
        }
        for item in operational["scenarios"]
    ] + [
        {
            "id": item["id"],
            "name": item["name"],
            "kind": "action",
            "predecessor_ids": [],
            "requirement_ids": [],
            "status": item.get("status", "accepted"),
        }
        for item in functional["functions"]
    ]
    activities.extend(
        {
            "id": item["id"],
            "name": item["name"],
            "kind": "analysis_gap",
            "predecessor_ids": [],
            "requirement_ids": [item.get("attributes", {}).get("requirement_id", "")],
            "status": "needs-analysis",
            "needs_analysis": True,
            "reason": item.get("attributes", {}).get("reason", ""),
        }
        for item in functional.get("gaps", ())
    )
    messages = []
    for index, scenario in enumerate(operational["scenarios"], start=1):
        actors_for_scenario = [
            relation["source_id"]
            for relation in model["relations"]
            if relation["kind"] == "participatesIn" and relation["target_id"] == scenario["id"]
        ]
        from_id = f"lifeline-{actors_for_scenario[0]}" if actors_for_scenario else "lifeline-system"
        flow = scenario.get("attributes", {}).get("interaction_steps", scenario.get("attributes", {}).get("steps", ()))
        flow = list(flow) if isinstance(flow, (list, tuple)) else []
        message_name = flow[0].get("message", "") if flow and isinstance(flow[0], dict) else (str(flow[0]) if flow else scenario["name"])
        messages.append(
            {
                "id": f"message-{canonical_hash((scenario['id'], index))[:12]}",
                "name": message_name or scenario["name"],
                "from_id": from_id,
                "to_id": "lifeline-system" if from_id != "lifeline-system" else from_id,
                "sequence": index,
                "requirement_ids": list(scenario.get("attributes", {}).get("requirement_ids", ())),
                "canonical_flow_id": scenario.get("attributes", {}).get("canonical_flow_id", ""),
                "canonical_flow_hash": scenario.get("attributes", {}).get("canonical_flow_hash", ""),
                "status": scenario.get("status", "accepted"),
            }
        )
    trace_links = [
        {
            "id": relation["id"],
            "source_id": relation["source_id"],
            "predicate": relation["kind"],
            "target_id": relation["target_id"],
            "status": "accepted",
            "producer": relation.get("producer", "rule"),
        }
        for relation in model["relations"]
        if relation["kind"] in {"derivedFrom", "satisfiedBy", "allocatedTo", "realizedBy", "refines", "verifiedBy"}
    ]
    return {
        "format": "ai4mbse/mbse",
        "version": 1,
        "semantic_model_version": MBSE_SEMANTIC_MODEL_VERSION,
        "status": "accepted",
        "review_history": [],
        "actors": sorted(actors, key=lambda item: str(item["id"])),
        "use_cases": sorted(use_cases, key=lambda item: str(item["id"])),
        "activities": sorted(activities, key=lambda item: str(item["id"])),
        "lifelines": sorted(lifelines, key=lambda item: str(item["id"])),
        "messages": sorted(messages, key=lambda item: str(item["id"])),
        "trace_links": sorted(trace_links, key=lambda item: (str(item["source_id"]), str(item["target_id"]))),
    }
