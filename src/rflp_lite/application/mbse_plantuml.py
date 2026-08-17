"""PlantUML compilers for sequence and activity MBSE views."""

from __future__ import annotations

from rflp_lite.application.mbse_views import semantic_model_for_view, view_definition, view_entities
from rflp_lite.domain.errors import ContractViolation


def _alias(value: object, prefix: str) -> str:
    text = "".join(char if char.isalnum() else "_" for char in str(value or ""))
    text = text.strip("_") or prefix
    return f"{prefix}_{text[:32]}"


def _safe_text(value: object) -> str:
    return str(value or "").replace("\n", " ").replace(":", "：")


def compile_plantuml_view(model: object, view_id: str, options: dict[str, object] | None = None) -> str:
    del options
    definition = view_definition(view_id)
    if definition.compiler != "plantuml":
        raise ContractViolation(f"view {definition.id} is not a PlantUML view")
    semantic = semantic_model_for_view(model)
    sections = semantic.get("sections", {})
    operational = sections.get("operational", {}) if isinstance(sections, dict) else {}
    functional = sections.get("functional", {}) if isinstance(sections, dict) else {}
    lines = ["@startuml", "hide footbox", "skinparam shadowing false", "skinparam roundcorner 12"]
    if definition.id == "operational_scenario":
        stakeholders = [item for item in operational.get("stakeholders", ()) if isinstance(item, dict)]
        scenarios = [item for item in operational.get("scenarios", ()) if isinstance(item, dict)]
        for item in stakeholders:
            lines.append(f"actor \"{_safe_text(item.get('name'))}\" as {_alias(item.get('id'), 'actor')}")
        lines.append('participant "系统边界" as system')
        for scenario in scenarios or [{"id": "scenario-empty", "name": "暂无运行场景", "attributes": {}}]:
            lines.append(f"== {_safe_text(scenario.get('name'))} ==")
            attributes = scenario.get("attributes", {}) if isinstance(scenario.get("attributes"), dict) else {}
            actors = attributes.get("actor_ids") or attributes.get("actors") or []
            actor_alias = _alias(actors[0], "actor") if actors else "system"
            steps = attributes.get("steps") or ["识别任务条件", "执行系统功能", "确认结果"]
            for step in steps:
                lines.append(f"{actor_alias} -> system: {_safe_text(step)}")
            lines.append("system --> " + actor_alias + ": 结果/状态")
    else:
        lines.extend(["start", "partition 功能场景 {"])
        functions = [item for item in functional.get("functions", ()) if isinstance(item, dict)]
        scenarios = [item for item in functional.get("scenarios", ()) if isinstance(item, dict)]
        for item in functions + scenarios:
            lines.append(f":{_safe_text(item.get('name'))};")
            if item.get("needs_analysis"):
                lines.append("note right: 待补充分析")
        if not functions and not scenarios:
            lines.append(":暂无功能场景;")
        lines.extend(["}", "stop"])
    lines.append("@enduml")
    return "\n".join(lines) + "\n"
