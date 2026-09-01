from __future__ import annotations

import json

from rflp_lite.application.intelligence.identity import (
    advance_content_revision,
    ensure_entity_metadata,
    ensure_workbench_metadata,
    entity_match_keys,
)
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


SCENARIO_MATRIX_LIMIT = 16

CORE_SCENARIO_TYPES = frozenset(
    {"normal", "boundary", "failure", "recovery", "misuse"}
)
CORE_SCENARIO_DIMENSIONS = frozenset(
    {
        "external_system_failure",
        "human_interaction_error",
        "performance_capacity_boundary",
        "safety",
        "cybersecurity",
        "regulatory",
    }
)
# These values predate the five-lens coverage audit and remain valid for
# existing generated scenario matrices and persisted workbenches.
_LEGACY_SCENARIO_TYPES = frozenset({"exception", "emergency"})
_EDITABLE_SCENARIO_FIELDS = (
    "title",
    "scenario_type",
    "coverage_dimensions",
    "lifecycle_phase",
    "description",
    "trigger",
    "actors",
    "stakeholder_ids",
    "preconditions",
    "steps",
    "recovery_steps",
    "expected_outcomes",
    "faults",
    "requirement_ids",
)

_SCENARIO_MATRIX_ROWS = (
    ("normal", "正常医疗转运", {"mission_phase": "城市巡航", "system_state": "正常", "medical_urgency": "常规转运"}),
    ("normal", "患者交接", {"mission_phase": "患者交接", "system_state": "正常"}),
    ("exception", "夜间低能见度", {"visibility": "夜间", "mission_phase": "接近医院"}),
    ("exception", "雨天运行", {"weather": "雨天", "mission_phase": "城市巡航"}),
    ("exception", "高峰人口密集区", {"time": "高峰", "urban_context": "人口密集区"}),
    ("failure", "通信中断", {"connectivity": "通信中断", "system_state": "降级"}),
    ("failure", "导航不可信", {"connectivity": "导航不可信", "system_state": "部分失效"}),
    ("failure", "强风或暴雨", {"weather": "强风", "system_state": "降级"}),
    ("failure", "起降点不可用", {"urban_context": "狭窄起降点", "mission_phase": "应急备降"}),
    ("emergency", "危重患者优先转运", {"medical_urgency": "危重", "mission_phase": "接警"}),
    ("emergency", "生命垂危紧急转运", {"medical_urgency": "生命垂危", "mission_phase": "医疗准备"}),
    ("emergency", "雷暴条件备降", {"weather": "雷暴", "mission_phase": "应急备降"}),
    ("emergency", "GNSS 受干扰", {"connectivity": "GNSS受干扰", "system_state": "失效安全"}),
    ("normal", "医院屋顶降落", {"urban_context": "医院屋顶", "mission_phase": "降落"}),
    ("exception", "灾害封锁区响应", {"urban_context": "灾害封锁区", "time": "灾害响应"}),
    ("failure", "完全失效后的安全处置", {"system_state": "完全失效", "mission_phase": "返航"}),
)


def _lines(value: str | list[str] | tuple[str, ...]) -> list[str]:
    values = value.splitlines() if isinstance(value, str) else list(value)
    return [item.strip() for item in values if str(item).strip()]


def _unique_lines(value: str | list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(_lines(value)))


def _configured_ids(state: dict[str, object], key: str) -> set[str]:
    config = state.get("analysis_config")
    guidance = config.get("guidance") if isinstance(config, dict) else None
    raw = guidance.get(key, ()) if isinstance(guidance, dict) else ()
    values: set[str] = set()
    for item in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(item, dict):
            for field in ("id", "label"):
                value = str(item.get(field, "")).strip()
                if value:
                    values.add(value)
        else:
            value = str(item).strip()
            if value:
                values.add(value)
    return values


def _validate_scenario_fields(
    state: dict[str, object],
    *,
    scenario_type: str,
    coverage_dimensions: list[str],
    lifecycle_phase: str,
) -> None:
    allowed_types = CORE_SCENARIO_TYPES | _LEGACY_SCENARIO_TYPES | _configured_ids(
        state, "scenario_types"
    )
    if scenario_type not in allowed_types:
        raise ContractViolation("场景类型无效")
    allowed_dimensions = CORE_SCENARIO_DIMENSIONS | _configured_ids(
        state, "scenario_dimensions"
    )
    unknown_dimensions = sorted(set(coverage_dimensions) - allowed_dimensions)
    if unknown_dimensions:
        raise ContractViolation(
            f"场景覆盖维度无效: {', '.join(unknown_dimensions)}"
        )
    configured_phases = _configured_ids(state, "lifecycle_phases")
    if lifecycle_phase and configured_phases and lifecycle_phase not in configured_phases:
        raise ContractViolation("场景生命周期阶段无效")


def _validate_scenario_relations(
    state: dict[str, object], scenario: dict[str, object]
) -> None:
    known_requirements = {
        str(item.get("id", ""))
        for item in state.get("claims", ())
        if isinstance(item, dict)
    }
    unknown_requirements = sorted(
        set(str(value) for value in scenario.get("requirement_ids", ()))
        - known_requirements
    )
    if unknown_requirements:
        raise ContractViolation(
            f"场景关联了不存在的 Requirement: {', '.join(unknown_requirements)}"
        )
    known_stakeholders = {
        str(item.get("id", ""))
        for item in state.get("stakeholders", ())
        if isinstance(item, dict)
    }
    unknown_stakeholders = sorted(
        set(str(value) for value in scenario.get("stakeholder_ids", ()))
        - known_stakeholders
    )
    if unknown_stakeholders:
        raise ContractViolation(
            f"场景关联了不存在的利益相关方: {', '.join(unknown_stakeholders)}"
        )


def _resolve_suggestions(
    item: dict[str, object], values: dict[str, object]
) -> None:
    history = list(item.get("suggestion_history", ()))
    remaining = []
    for suggestion in item.get("suggested_changes", ()):
        if not isinstance(suggestion, dict):
            continue
        field = str(suggestion.get("field", ""))
        if field in values and values[field] == suggestion.get("suggested"):
            history.append({**suggestion, "status": "accepted_by_user"})
        else:
            remaining.append(suggestion)
    item["suggested_changes"] = remaining
    item["suggestion_history"] = history


def _invalidate_analysis_outputs(result: dict[str, object]) -> None:
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["draft_graph"] = None
    result["mbse"] = None
    result["baseline"], result["project"] = None, None
    result["analysis_coverage"] = {}


def _required_lines(value: str | list[str] | tuple[str, ...], label: str) -> list[str]:
    values = _lines(value)
    if not values:
        raise ContractViolation(f"场景{label}不能为空")
    return values


def build_scenario(
    *,
    title: str,
    scenario_type: str = "normal",
    coverage_dimensions: str | list[str] | tuple[str, ...] = (),
    lifecycle_phase: str = "",
    description: str,
    trigger: str = "",
    actors: str | list[str] | tuple[str, ...] = (),
    stakeholder_ids: str | list[str] | tuple[str, ...] = (),
    preconditions: str | list[str] | tuple[str, ...] = (),
    steps: str | list[str] | tuple[str, ...],
    recovery_steps: str | list[str] | tuple[str, ...] = (),
    expected_outcomes: str | list[str] | tuple[str, ...],
    faults: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    clean_title = title.strip()
    clean_description = description.strip()
    clean_scenario_type = str(scenario_type).strip().casefold() or "normal"
    if not clean_title:
        raise ContractViolation("场景标题不能为空")
    if not clean_description:
        raise ContractViolation("场景描述不能为空")
    if clean_scenario_type not in CORE_SCENARIO_TYPES | _LEGACY_SCENARIO_TYPES:
        raise ContractViolation("场景类型无效")
    payload = {
        "title": clean_title,
        "scenario_type": clean_scenario_type,
        "coverage_dimensions": _unique_lines(coverage_dimensions),
        "lifecycle_phase": str(lifecycle_phase).strip(),
        "description": clean_description,
        "trigger": str(trigger).strip(),
        "actors": _lines(actors),
        "stakeholder_ids": sorted(set(_lines(stakeholder_ids))),
        "preconditions": _lines(preconditions),
        "steps": _required_lines(steps, "步骤"),
        "recovery_steps": _lines(recovery_steps),
        "expected_outcomes": _required_lines(expected_outcomes, "预期结果"),
        "faults": _lines(faults),
        "requirement_ids": sorted(set(_lines(requirement_ids))),
    }
    digest = canonical_hash(payload)
    return {
        "id": f"scenario-{digest[:12]}",
        **payload,
        "status": "accepted",
        "revision": 1,
        "review_history": (),
        "hash": digest,
    }


def add_scenario(
    state: dict[str, object],
    *,
    title: str,
    scenario_type: str = "normal",
    coverage_dimensions: str | list[str] | tuple[str, ...] = (),
    lifecycle_phase: str = "",
    description: str,
    trigger: str = "",
    actors: str | list[str] | tuple[str, ...] = (),
    stakeholder_ids: str | list[str] | tuple[str, ...] = (),
    preconditions: str | list[str] | tuple[str, ...] = (),
    steps: str | list[str] | tuple[str, ...],
    recovery_steps: str | list[str] | tuple[str, ...] = (),
    expected_outcomes: str | list[str] | tuple[str, ...],
    faults: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
    human_change: bool = True,
) -> dict[str, object]:
    scenario = build_scenario(
        title=title,
        scenario_type=scenario_type,
        coverage_dimensions=coverage_dimensions,
        lifecycle_phase=lifecycle_phase,
        description=description,
        trigger=trigger,
        actors=actors,
        stakeholder_ids=stakeholder_ids,
        preconditions=preconditions,
        steps=steps,
        recovery_steps=recovery_steps,
        expected_outcomes=expected_outcomes,
        faults=faults,
        requirement_ids=requirement_ids,
    )
    result = ensure_workbench_metadata(state)
    _validate_scenario_fields(
        result,
        scenario_type=str(scenario["scenario_type"]),
        coverage_dimensions=list(scenario["coverage_dimensions"]),
        lifecycle_phase=str(scenario["lifecycle_phase"]),
    )
    _validate_scenario_relations(result, scenario)
    editor = "user" if human_change else "rule"
    scenario["producer"] = editor
    scenario = ensure_entity_metadata("scenario", scenario, editor=editor)
    scenarios = [item for item in result.get("scenarios", ()) if item["id"] != scenario["id"]]
    scenarios.append(scenario)
    result["scenarios"] = sorted(scenarios, key=lambda item: item["id"])
    if human_change:
        _invalidate_analysis_outputs(result)
        return advance_content_revision(result)
    return result


def _generated_payload(
    state: dict[str, object], claim: dict[str, object] | None = None
) -> dict[str, object]:
    context = state.get("system_context") or {}
    system_name = str(context.get("name") or "待命名系统").strip()
    if claim is None:
        objective = f"明确{system_name}的系统目标"
        actor = "需求提出者"
        requirement_ids: tuple[str, ...] = ()
    else:
        objective = str(claim.get("object") or "完成系统目标").strip().rstrip("。.!！?？")
        actor = str(claim.get("subject") or "使用者").strip()
        requirement_ids = (str(claim["id"]),)
    actor = actor or "使用者"
    return {
        "title": f"{actor}：{objective[:28]}",
        "description": (
            f"根据需求“{objective}”生成的最小可执行场景，围绕当前输入自动展开。"
            "缺少的信息先标记为待确认，不阻塞继续查看和生成模型。"
        ),
        "actors": (actor, "系统"),
        "preconditions": (),
        "steps": (
            f"{actor}提出目标：{objective}",
            f"系统处理：{objective}",
            "确认系统输出和验证结果",
        ),
        "expected_outcomes": (f"系统完成：{objective}",),
        "faults": (),
        "requirement_ids": requirement_ids,
    }


def generate_scenario_drafts(state: dict[str, object]) -> dict[str, object]:
    """Generate viewable starter scenarios from the smallest available input."""
    result = json.loads(canonical_json(state))
    if result.get("scenarios"):
        return result

    claims = tuple(
        item
        for item in result.get("claims", ())
        if item.get("status") != "rejected"
    )
    sources: tuple[dict[str, object] | None, ...] = claims or (None,)
    generated: list[dict[str, object]] = []
    for claim in sources:
        payload = _generated_payload(result, claim)
        scenario = build_scenario(**payload)
        scenario.update(
            {
                "status": "accepted",
                "producer": "system",
                "generated_from": str(claim["id"]) if claim else "system-context",
                "generation_mode": "minimum-input",
            }
        )
        generated.append(scenario)
    result["scenarios"] = sorted(generated, key=lambda item: item["id"])
    return result


def _scenario_dimension_values(pack: dict[str, object]) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    dimensions = pack.get("scenario_dimensions", ())
    for item in dimensions if isinstance(dimensions, list) else ():
        if not isinstance(item, dict):
            continue
        dimension_id = str(item.get("id", "")).strip()
        raw_values = item.get("values", ())
        if dimension_id and isinstance(raw_values, list):
            values[dimension_id] = {str(value) for value in raw_values if str(value).strip()}
    return values


def _scenario_claim(state: dict[str, object]) -> dict[str, object] | None:
    claims = [
        item
        for item in state.get("claims", ())
        if isinstance(item, dict) and item.get("status") != "rejected"
    ]
    if claims:
        return claims[0]
    requirements = [
        item
        for item in state.get("structured_requirements", ())
        if isinstance(item, dict) and item.get("status") != "rejected"
    ]
    return requirements[0] if requirements else None


def _scenario_actors(state: dict[str, object], claim: dict[str, object] | None) -> tuple[str, ...]:
    names = [
        str(item.get("name", "")).strip()
        for item in state.get("stakeholders", ())
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    if not names and claim is not None:
        names.append(str(claim.get("subject", "使用者")).strip() or "使用者")
    return tuple(dict.fromkeys([*names[:2], "系统"]))


def _scenario_lifecycle_phase(pack: dict[str, object], dimensions: dict[str, str]) -> str:
    phase = dimensions.get("mission_phase", "")
    phases = pack.get("lifecycle_phases", ())
    if phase:
        for item in phases if isinstance(phases, list) else ():
            if isinstance(item, dict) and phase in str(item.get("label", "")):
                return str(item.get("label", phase))
        return phase
    first = phases[0] if isinstance(phases, list) and phases and isinstance(phases[0], dict) else {}
    return str(first.get("label", "运行"))


def _scenario_type_label(scenario_type: str) -> str:
    return {
        "normal": "正常场景",
        "exception": "异常场景",
        "failure": "故障场景",
        "emergency": "应急场景",
    }.get(scenario_type, "场景")


def _untouched_automatic_scenario(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return (
        str(item.get("producer", "")) == "system"
        and str(item.get("generation_mode", "")) in {"minimum-input", "scenario-matrix"}
        and int(item.get("revision", 1) or 1) <= 1
        and not item.get("review_history")
    )


def generate_scenario_matrix(
    state: dict[str, object],
    pack: dict[str, object],
    *,
    limit: int = SCENARIO_MATRIX_LIMIT,
) -> dict[str, object]:
    """Generate representative normal, exception, failure, and emergency scenarios."""

    try:
        bounded_limit = max(12, min(20, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = SCENARIO_MATRIX_LIMIT
    result = json.loads(canonical_json(state))
    claim = _scenario_claim(result)
    objective = str((claim or {}).get("object") or (claim or {}).get("statement") or "完成系统目标").strip().rstrip("。.!！?？")
    requirement_ids = (str(claim.get("id")),) if claim and claim.get("id") else ()
    actors = _scenario_actors(result, claim)
    available = _scenario_dimension_values(pack)
    generated: list[dict[str, object]] = []
    for scenario_type, label, requested_dimensions in _SCENARIO_MATRIX_ROWS[:bounded_limit]:
        dimensions = {
            key: value
            for key, value in requested_dimensions.items()
            if not available.get(key) or value in available[key]
        }
        if not dimensions:
            dimensions = {"scenario_type": scenario_type}
        lifecycle_phase = _scenario_lifecycle_phase(pack, dimensions)
        type_label = _scenario_type_label(scenario_type)
        fault = (
            f"{label}发生时，系统识别风险并进入安全处置。"
            if scenario_type in {"failure", "emergency"}
            else "无异常；按正常流程完成任务。"
        )
        scenario = build_scenario(
            title=f"{type_label}：{label}",
            description=f"围绕需求“{objective}”生成的{type_label}，用于验证{label}条件下的系统行为。",
            actors=actors,
            preconditions=("任务已创建", "参与者和系统资源已就绪"),
            steps=(
                f"识别场景条件：{label}",
                f"系统执行与“{objective[:36]}”相关的任务流程",
                "监控状态并记录关键事件",
                "完成结果确认或安全处置",
            ),
            expected_outcomes=(
                f"系统在{label}条件下完成任务或进入可控安全状态",
                "输出可追溯的场景结果",
            ),
            faults=(fault,),
            requirement_ids=requirement_ids,
        )
        identity = canonical_hash((requirement_ids, scenario_type, label, dimensions))
        scenario.update(
            {
                "id": f"scenario-{identity[:12]}",
                "hash": identity,
                "scenario_type": scenario_type,
                "dimensions": dimensions,
                "lifecycle_phase": lifecycle_phase,
                "producer": "system",
                "generated_from": str(claim.get("id", "system-context")) if claim else "system-context",
                "generation_mode": "scenario-matrix",
            }
        )
        generated.append(scenario)

    preserved = [
        item
        for item in result.get("scenarios", ())
        if isinstance(item, dict) and not _untouched_automatic_scenario(item)
    ]
    result["scenarios"] = sorted(preserved + generated, key=lambda item: (str(item.get("scenario_type", "manual")), str(item.get("title", "")), str(item.get("id", ""))))
    return result


def revise_scenario(
    state: dict[str, object],
    scenario_id: str,
    *,
    title: str,
    scenario_type: str | None = None,
    coverage_dimensions: str | list[str] | tuple[str, ...] | None = None,
    lifecycle_phase: str | None = None,
    description: str,
    trigger: str | None = None,
    actors: str | list[str] | tuple[str, ...] = (),
    stakeholder_ids: str | list[str] | tuple[str, ...] | None = None,
    preconditions: str | list[str] | tuple[str, ...] = (),
    steps: str | list[str] | tuple[str, ...],
    recovery_steps: str | list[str] | tuple[str, ...] | None = None,
    expected_outcomes: str | list[str] | tuple[str, ...],
    faults: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    """Edit a scenario and keep the revised version active immediately."""

    result = ensure_workbench_metadata(state)
    existing = next(
        (item for item in result.get("scenarios", ()) if item.get("id") == scenario_id),
        None,
    )
    if existing is None:
        raise ContractViolation("场景不存在")
    resolved_type = (
        str(scenario_type).strip().casefold()
        if scenario_type is not None
        else str(existing.get("scenario_type", "normal")).strip().casefold()
    ) or "normal"
    resolved_dimensions = (
        coverage_dimensions
        if coverage_dimensions is not None
        else existing.get("coverage_dimensions", ())
    )
    resolved_lifecycle = (
        str(lifecycle_phase).strip()
        if lifecycle_phase is not None
        else str(existing.get("lifecycle_phase", ""))
    )
    resolved_trigger = (
        str(trigger).strip()
        if trigger is not None
        else str(existing.get("trigger", ""))
    )
    resolved_stakeholders = (
        stakeholder_ids
        if stakeholder_ids is not None
        else existing.get("stakeholder_ids", ())
    )
    resolved_recovery_steps = (
        recovery_steps
        if recovery_steps is not None
        else existing.get("recovery_steps", ())
    )
    updated = build_scenario(
        title=title,
        scenario_type=resolved_type,
        coverage_dimensions=resolved_dimensions,  # type: ignore[arg-type]
        lifecycle_phase=resolved_lifecycle,
        description=description,
        trigger=resolved_trigger,
        actors=actors,
        stakeholder_ids=resolved_stakeholders,  # type: ignore[arg-type]
        preconditions=preconditions,
        steps=steps,
        recovery_steps=resolved_recovery_steps,  # type: ignore[arg-type]
        expected_outcomes=expected_outcomes,
        faults=faults,
        requirement_ids=requirement_ids,
    )
    _validate_scenario_fields(
        result,
        scenario_type=str(updated["scenario_type"]),
        coverage_dimensions=list(updated["coverage_dimensions"]),
        lifecycle_phase=str(updated["lifecycle_phase"]),
    )
    _validate_scenario_relations(result, updated)
    revision = int(existing.get("revision", 1)) + 1
    updated["id"] = scenario_id
    updated["revision"] = revision
    updated["status"] = "accepted"
    updated["producer"] = existing.get("producer", "user")
    updated["generated_from"] = existing.get("generated_from", "")
    updated["generation_mode"] = existing.get("generation_mode", "manual")
    if "dimensions" in existing:
        updated["dimensions"] = existing["dimensions"]
    updated["review_history"] = tuple(existing.get("review_history", ()))
    updated["last_editor"] = "user"
    submitted_fields = {
        "title": updated["title"],
        "description": updated["description"],
        "actors": updated["actors"],
        "preconditions": updated["preconditions"],
        "steps": updated["steps"],
        "expected_outcomes": updated["expected_outcomes"],
        "faults": updated["faults"],
        "requirement_ids": updated["requirement_ids"],
    }
    optional_submissions = {
        "scenario_type": scenario_type,
        "coverage_dimensions": coverage_dimensions,
        "lifecycle_phase": lifecycle_phase,
        "trigger": trigger,
        "stakeholder_ids": stakeholder_ids,
        "recovery_steps": recovery_steps,
    }
    for field, raw_value in optional_submissions.items():
        if raw_value is not None:
            submitted_fields[field] = updated[field]
    updated["field_sources"] = {
        **dict(existing.get("field_sources") or {}),
        **{field: "user" for field in submitted_fields},
    }
    updated["suggested_changes"] = list(existing.get("suggested_changes", ()))
    updated["suggestion_history"] = list(existing.get("suggestion_history", ()))
    updated["aliases"] = list(existing.get("aliases", ()))
    _resolve_suggestions(updated, submitted_fields)
    updated["match_keys"] = sorted(
        set(existing.get("match_keys", ()))
        | set(entity_match_keys("scenario", updated))
    )
    updated.setdefault("source_requirement_ids", list(updated["requirement_ids"]))
    updated.setdefault("review_hint", str(existing.get("review_hint", "")))
    updated.setdefault("identity_hash", existing.get("identity_hash", ""))
    updated["hash"] = canonical_hash(
        {key: value for key, value in updated.items() if key not in {"review_history", "hash", "status"}}
    )
    result["scenarios"] = sorted(
        [item for item in result.get("scenarios", ()) if item.get("id") != scenario_id] + [updated],
        key=lambda item: str(item["id"]),
    )
    _invalidate_analysis_outputs(result)
    return advance_content_revision(result)


def review_scenario(
    state: dict[str, object], scenario_id: str, decision: str
) -> dict[str, object]:
    """Accept or reject a scenario and retain an immutable decision trail."""

    if decision not in {"accepted", "rejected"}:
        raise ContractViolation("场景确认结果必须是 accepted 或 rejected")
    result = ensure_workbench_metadata(state)
    scenario = next(
        (item for item in result.get("scenarios", ()) if item.get("id") == scenario_id),
        None,
    )
    if scenario is None:
        raise ContractViolation("场景不存在")
    if not scenario.get("steps") or not scenario.get("expected_outcomes"):
        raise ContractViolation("场景必须先填写步骤和预期结果")
    history = list(scenario.get("review_history", ()))
    history.append(
        {
            "from": str(scenario.get("status", "draft")),
            "to": decision,
            "revision": int(scenario.get("revision", 1)),
            "decision_hash": canonical_hash((scenario_id, scenario.get("hash", ""), decision, len(history) + 1)),
        }
    )
    scenario["review_history"] = history
    scenario["status"] = decision
    scenario["last_editor"] = "user"
    scenario["field_sources"] = {
        **dict(scenario.get("field_sources") or {}),
        "status": "user",
    }
    result["scenarios"] = sorted(result.get("scenarios", ()), key=lambda item: str(item["id"]))
    _invalidate_analysis_outputs(result)
    return advance_content_revision(result)


def delete_scenario(state: dict[str, object], scenario_id: str) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    existing = result.get("scenarios", ())
    if not any(item.get("id") == scenario_id for item in existing):
        raise ContractViolation("场景不存在")
    result["scenarios"] = [item for item in existing if item.get("id") != scenario_id]
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["mbse"] = None
    result["baseline"], result["project"] = None, None
    return result
