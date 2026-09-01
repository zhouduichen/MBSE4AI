"""Registry and semantic selection rules for professional MBSE views."""

from __future__ import annotations

from importlib import import_module

from dataclasses import dataclass

from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class MBSEViewDefinition:
    id: str
    label: str
    description: str
    compiler: str
    layout: str
    aliases: tuple[str, ...] = ()


MBSE_VIEW_DEFINITIONS: tuple[MBSEViewDefinition, ...] = (
    MBSEViewDefinition("environment", "系统环境图", "系统边界、外部环境与交换对象", "graphviz", "radial"),
    MBSEViewDefinition("stakeholder_hierarchy", "利益相关方层级", "利益相关方、关注点与需要层级", "graphviz", "hierarchy"),
    MBSEViewDefinition("requirements_tree", "需求分类树", "需求与技术需求分类分解", "graphviz", "tree", ("requirements",)),
    MBSEViewDefinition("lifecycle", "生命周期图", "阶段、状态与转移关系", "graphviz", "flow"),
    MBSEViewDefinition("use_case_tree", "用例树", "任务场景与参与者目标", "graphviz", "tree", ("use_case",)),
    MBSEViewDefinition("operational_scenario", "运行场景顺序图", "参与者、系统边界与时间顺序", "plantuml", "sequence", ("sequence",)),
    MBSEViewDefinition("function_tree", "功能分解树", "功能层级与需求满足关系", "graphviz", "tree", ("activity",)),
    MBSEViewDefinition("function_interaction", "功能交互图", "功能之间的输入输出流", "graphviz", "flow"),
    MBSEViewDefinition("functional_scenario", "功能场景活动图", "功能活动、条件与结果", "plantuml", "activity"),
    MBSEViewDefinition("logical_tree", "逻辑架构树", "逻辑组件分解", "graphviz", "tree"),
    MBSEViewDefinition("logical_interaction", "逻辑交互图", "逻辑组件与接口流", "graphviz", "flow"),
    MBSEViewDefinition("allocation_matrix", "分配矩阵", "功能到逻辑/物理实现分配", "matrix", "matrix"),
    MBSEViewDefinition("physical_interaction", "物理交互图", "物理构件与接口方向", "graphviz", "flow"),
    MBSEViewDefinition("technical_requirements", "技术需求树", "可验证技术需求及其来源", "graphviz", "tree"),
    MBSEViewDefinition("traceability_matrix", "追溯矩阵", "跨层级满足、分配和实现关系", "matrix", "matrix", ("traceability",)),
    MBSEViewDefinition("rflp", "RFLP 总览", "需求—功能—逻辑—物理主链路", "graphviz", "flow", ("all",)),
)


def _definition(view_id: str) -> MBSEViewDefinition:
    clean = str(view_id or "").strip()
    for definition in MBSE_VIEW_DEFINITIONS:
        if clean == definition.id or clean in definition.aliases:
            return definition
    raise ContractViolation(f"unsupported MBSE view: {clean}")


def semantic_model_for_view(model: object) -> dict[str, object]:
    if not isinstance(model, dict):
        raise ContractViolation("MBSE model must be an object")
    semantic = model.get("semantic_model")
    if isinstance(semantic, dict):
        return semantic
    if model.get("format") == "ai4mbse/mbse-semantic":
        return model
    # Compatibility adapter for old callers that pass a v1 model directly.
    actors = [dict(item) for item in model.get("actors", ()) if isinstance(item, dict)]
    use_cases = [dict(item) for item in model.get("use_cases", ()) if isinstance(item, dict)]
    activities = [dict(item) for item in model.get("activities", ()) if isinstance(item, dict)]
    return {
        "format": "ai4mbse/mbse-semantic",
        "version": 2,
        "workspace": "legacy",
        "revision": str(model.get("revision", "legacy")),
        "provenance": {"producer": "legacy-projection"},
        "sections": {
            "operational": {
                "environment": [],
                "sources": [],
                "stakeholders": [
                    {
                        "id": item.get("id"),
                        "kind": "stakeholder",
                        "name": item.get("name", item.get("id")),
                        "status": item.get("status", "accepted"),
                        "producer": "legacy-projection",
                        "source": {"span_ids": [], "input_hash": ""},
                        "needs_analysis": False,
                        "attributes": {},
                    }
                    for item in actors
                ],
                "stakeholder_hierarchy": [],
                "concerns": [],
                "needs": [],
                "use_cases": [],
                "lifecycle": [],
                "scenarios": [
                    {
                        "id": item.get("id"),
                        "kind": "operational_scenario",
                        "name": item.get("name", item.get("id")),
                        "status": item.get("status", "accepted"),
                        "producer": "legacy-projection",
                        "source": {"span_ids": [], "input_hash": ""},
                        "needs_analysis": False,
                        "attributes": {"actor_ids": item.get("actor_ids", ())},
                    }
                    for item in use_cases
                ],
            },
            "functional": {
                "requirements": [],
                "functions": [
                    {
                        "id": item.get("id"),
                        "kind": "function",
                        "name": item.get("name", item.get("id")),
                        "status": item.get("status", "accepted"),
                        "producer": "legacy-projection",
                        "source": {"span_ids": [], "input_hash": ""},
                        "needs_analysis": False,
                        "attributes": {},
                    }
                    for item in activities
                ],
                "flows": [],
                "scenarios": [],
            },
            "logical": {"components": [], "flows": [], "interfaces": []},
            "physical": {"components": [], "flows": [], "interfaces": [], "allocations": []},
            "technical_requirements": [],
        },
        "relations": [
            {
                "id": str(item.get("id", "legacy-relation")),
                "source_id": str(item.get("source_id", "")),
                "kind": str(item.get("predicate", "relatedTo")),
                "target_id": str(item.get("target_id", "")),
                "producer": "legacy-projection",
                "confidence": 1.0,
                "evidence": [],
            }
            for item in model.get("trace_links", ())
            if isinstance(item, dict) and item.get("source_id") and item.get("target_id")
        ],
    }


def _entities(section: object, *keys: str) -> list[dict[str, object]]:
    if not isinstance(section, dict):
        return []
    result: list[dict[str, object]] = []
    for key in keys:
        result.extend(item for item in section.get(key, ()) if isinstance(item, dict) and item.get("id"))
    return result


def view_entities(model: object, view_id: str) -> list[dict[str, object]]:
    definition = _definition(view_id)
    semantic = semantic_model_for_view(model)
    sections = semantic.get("sections", {})
    operational = sections.get("operational", {}) if isinstance(sections, dict) else {}
    functional = sections.get("functional", {}) if isinstance(sections, dict) else {}
    logical = sections.get("logical", {}) if isinstance(sections, dict) else {}
    physical = sections.get("physical", {}) if isinstance(sections, dict) else {}
    technical = sections.get("technical_requirements", []) if isinstance(sections, dict) else []
    mapping = {
        "environment": _entities(operational, "environment", "sources", "stakeholders"),
        "stakeholder_hierarchy": _entities(operational, "stakeholders", "concerns", "needs"),
        "requirements_tree": _entities(functional, "requirements") + _entities({"items": technical}, "items"),
        "lifecycle": _entities(operational, "lifecycle"),
        "use_case_tree": _entities(operational, "scenarios"),
        "operational_scenario": _entities(operational, "scenarios", "stakeholders"),
        "function_tree": _entities(functional, "functions", "gaps"),
        "function_interaction": _entities(functional, "functions", "gaps"),
        "functional_scenario": _entities(functional, "functions", "scenarios", "gaps"),
        "logical_tree": _entities(logical, "components", "gaps"),
        "logical_interaction": _entities(logical, "components", "interfaces", "gaps"),
        "allocation_matrix": _entities(functional, "functions", "gaps") + _entities(logical, "components", "gaps") + _entities(physical, "components", "gaps"),
        "physical_interaction": _entities(physical, "components", "interfaces", "gaps"),
        "technical_requirements": _entities({"items": technical}, "items"),
        "traceability_matrix": [],
        "rflp": _entities(functional, "requirements", "functions", "gaps") + _entities(logical, "components", "gaps") + _entities(physical, "components", "gaps"),
    }
    return sorted(mapping.get(definition.id, []), key=lambda item: (str(item.get("kind", "")), str(item.get("name", "")), str(item.get("id", ""))))


def view_relations(model: object, view_id: str) -> list[dict[str, object]]:
    definition = _definition(view_id)
    semantic = semantic_model_for_view(model)
    entities = {str(item["id"]) for item in view_entities(semantic, definition.id)}
    if definition.id in {"allocation_matrix", "traceability_matrix"}:
        return [dict(item) for item in semantic.get("relations", ()) if isinstance(item, dict)]
    return [
        dict(item)
        for item in semantic.get("relations", ())
        if isinstance(item, dict)
        and str(item.get("source_id", "")) in entities
        and str(item.get("target_id", "")) in entities
    ]


def list_mbse_views(model: object) -> tuple[dict[str, object], ...]:
    semantic = semantic_model_for_view(model)
    result = []
    for definition in MBSE_VIEW_DEFINITIONS:
        entities = view_entities(semantic, definition.id)
        needs_analysis = any(bool(item.get("needs_analysis")) for item in entities)
        result.append(
            {
                "id": definition.id,
                "label": definition.label,
                "description": definition.description,
                "compiler": definition.compiler,
                "layout": definition.layout,
                "status": "needs-analysis" if needs_analysis else "ready" if entities else "empty",
                "node_count": len(entities),
                "relation_count": len(view_relations(semantic, definition.id)),
            }
        )
    return tuple(result)


def view_definition(view_id: str) -> MBSEViewDefinition:
    return _definition(view_id)


def compile_mbse_view(
    model: object, view_id: str, options: dict[str, object] | None = None
) -> dict[str, object]:
    """Compile one semantic view without invoking an external renderer."""

    definition = _definition(view_id)
    if definition.compiler == "graphviz":
        compiler = import_module("rflp_lite.application.mbse_graphviz")
        source = compiler.compile_graphviz_view(model, definition.id, options)
        metadata = compiler.graphviz_view_metadata(model, definition.id)
    elif definition.compiler == "plantuml":
        compiler = import_module("rflp_lite.application.mbse_plantuml")
        source = compiler.compile_plantuml_view(model, definition.id, options)
        metadata = {
            "view_id": definition.id,
            "layout": definition.layout,
            "nodes": tuple(view_entities(model, definition.id)),
            "edges": tuple(view_relations(model, definition.id)),
        }
    else:
        compiler = import_module("rflp_lite.application.mbse_matrix")
        source = ""
        metadata = compiler.matrix_view_data(model, definition.id)
    return {
        "view_id": definition.id,
        "title": definition.label,
        "compiler": definition.compiler,
        "layout": definition.layout,
        "source": source,
        **metadata,
    }
