from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


SCENARIO_MATRIX_LIMIT = 16

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


def _required_lines(value: str | list[str] | tuple[str, ...], label: str) -> list[str]:
    values = _lines(value)
    if not values:
        raise ContractViolation(f"场景{label}不能为空")
    return values


def build_scenario(
    *,
    title: str,
    description: str,
    actors: str | list[str] | tuple[str, ...] = (),
    preconditions: str | list[str] | tuple[str, ...] = (),
    steps: str | list[str] | tuple[str, ...],
    expected_outcomes: str | list[str] | tuple[str, ...],
    faults: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    clean_title = title.strip()
    clean_description = description.strip()
    if not clean_title:
        raise ContractViolation("场景标题不能为空")
    if not clean_description:
        raise ContractViolation("场景描述不能为空")
    payload = {
        "title": clean_title,
        "description": clean_description,
        "actors": _lines(actors),
        "preconditions": _lines(preconditions),
        "steps": _required_lines(steps, "步骤"),
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
    description: str,
    actors: str | list[str] | tuple[str, ...] = (),
    preconditions: str | list[str] | tuple[str, ...] = (),
    steps: str | list[str] | tuple[str, ...],
    expected_outcomes: str | list[str] | tuple[str, ...],
    faults: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    scenario = build_scenario(
        title=title,
        description=description,
        actors=actors,
        preconditions=preconditions,
        steps=steps,
        expected_outcomes=expected_outcomes,
        faults=faults,
        requirement_ids=requirement_ids,
    )
    claims = {str(item["id"]) for item in state.get("claims", ())}
    unknown = sorted(set(scenario["requirement_ids"]) - claims)
    if unknown:
        raise ContractViolation(f"场景关联了不存在的 Requirement: {', '.join(unknown)}")
    result = json.loads(canonical_json(state))
    scenarios = [item for item in result.get("scenarios", ()) if item["id"] != scenario["id"]]
    scenarios.append(scenario)
    result["scenarios"] = sorted(scenarios, key=lambda item: item["id"])
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
    description: str,
    actors: str | list[str] | tuple[str, ...] = (),
    preconditions: str | list[str] | tuple[str, ...] = (),
    steps: str | list[str] | tuple[str, ...],
    expected_outcomes: str | list[str] | tuple[str, ...],
    faults: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    """Edit a scenario and keep the revised version active immediately."""

    result = json.loads(canonical_json(state))
    existing = next(
        (item for item in result.get("scenarios", ()) if item.get("id") == scenario_id),
        None,
    )
    if existing is None:
        raise ContractViolation("场景不存在")
    updated = build_scenario(
        title=title,
        description=description,
        actors=actors,
        preconditions=preconditions,
        steps=steps,
        expected_outcomes=expected_outcomes,
        faults=faults,
        requirement_ids=requirement_ids,
    )
    claims = {str(item["id"]) for item in result.get("claims", ())}
    unknown = sorted(set(updated["requirement_ids"]) - claims)
    if unknown:
        raise ContractViolation(f"场景关联了不存在的 Requirement: {', '.join(unknown)}")
    revision = int(existing.get("revision", 1)) + 1
    updated["id"] = scenario_id
    updated["revision"] = revision
    updated["status"] = "accepted"
    updated["producer"] = existing.get("producer", "user")
    updated["generated_from"] = existing.get("generated_from", "")
    updated["generation_mode"] = existing.get("generation_mode", "manual")
    for key in ("scenario_type", "dimensions", "lifecycle_phase"):
        if key in existing:
            updated[key] = existing[key]
    updated["review_history"] = tuple(existing.get("review_history", ()))
    updated["hash"] = canonical_hash(
        {key: value for key, value in updated.items() if key not in {"review_history", "hash", "status"}}
    )
    result["scenarios"] = sorted(
        [item for item in result.get("scenarios", ()) if item.get("id") != scenario_id] + [updated],
        key=lambda item: str(item["id"]),
    )
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["mbse"] = None
    result["baseline"], result["project"] = None, None
    return result


def review_scenario(
    state: dict[str, object], scenario_id: str, decision: str
) -> dict[str, object]:
    """Accept or reject a scenario and retain an immutable decision trail."""

    if decision not in {"accepted", "rejected"}:
        raise ContractViolation("场景确认结果必须是 accepted 或 rejected")
    result = json.loads(canonical_json(state))
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
    result["scenarios"] = sorted(result.get("scenarios", ()), key=lambda item: str(item["id"]))
    return result


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
