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


def delete_scenario(state: dict[str, object], scenario_id: str) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    existing = result.get("scenarios", ())
    if not any(item.get("id") == scenario_id for item in existing):
        raise ContractViolation("场景不存在")
    result["scenarios"] = [item for item in existing if item.get("id") != scenario_id]
    return result
