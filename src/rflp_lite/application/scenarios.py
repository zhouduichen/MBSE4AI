from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


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
        "status": "draft",
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
            f"系统根据当前输入自动生成的初始场景，围绕“{objective}”展开。"
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
                "status": "generated-draft",
                "producer": "system",
                "generated_from": str(claim["id"]) if claim else "system-context",
                "generation_mode": "minimum-input",
            }
        )
        generated.append(scenario)
    result["scenarios"] = sorted(generated, key=lambda item: item["id"])
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
    """Edit a scenario and return it to the review gate."""

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
    updated["status"] = "draft"
    updated["producer"] = existing.get("producer", "user")
    updated["generated_from"] = existing.get("generated_from", "")
    updated["generation_mode"] = existing.get("generation_mode", "manual")
    updated["review_history"] = tuple(existing.get("review_history", ()))
    updated["hash"] = canonical_hash(
        {key: value for key, value in updated.items() if key not in {"review_history", "hash", "status"}}
    )
    result["scenarios"] = sorted(
        [item for item in result.get("scenarios", ()) if item.get("id") != scenario_id] + [updated],
        key=lambda item: str(item["id"]),
    )
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
    return result
