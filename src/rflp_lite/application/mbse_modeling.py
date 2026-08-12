"""Deterministic semantic Use Case, activity and sequence model generation."""

from __future__ import annotations

import json
from typing import Any

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _unique(values: list[dict[str, object]]) -> list[dict[str, object]]:
    return list({str(value["id"]): value for value in values}.values())


def _clone(state: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(state))


def generate_mbse_revision(state: dict[str, object]) -> dict[str, object]:
    accepted = [
        item for item in state.get("structured_requirements", ())
        if item.get("status") == "accepted"
    ]
    if not accepted:
        raise ContractViolation("请先接受至少一条结构化需求")
    actors: list[dict[str, object]] = []
    use_cases: list[dict[str, object]] = []
    activities: list[dict[str, object]] = []
    lifelines: list[dict[str, object]] = [{"id": "lifeline-system", "name": "系统", "status": "accepted"}]
    messages: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    for requirement in accepted:
        requirement_id = str(requirement["id"])
        subject = str(requirement.get("subject") or "使用者")
        actor_id = f"actor-{canonical_hash((subject,))[:12]}"
        use_case_id = f"usecase-{canonical_hash((requirement_id,))[:12]}"
        activity_id = f"activity-{canonical_hash((requirement_id, 'main'))[:12]}"
        message_id = f"message-{canonical_hash((requirement_id, 'request'))[:12]}"
        actors.append({"id": actor_id, "name": subject, "status": "accepted", "requirement_ids": [requirement_id]})
        use_cases.append({"id": use_case_id, "name": str(requirement.get("statement", requirement.get("object", ""))), "actor_ids": [actor_id], "requirement_ids": [requirement_id], "status": "accepted"})
        activities.append({"id": activity_id, "name": str(requirement.get("statement", requirement.get("object", ""))), "kind": "action", "predecessor_ids": [], "requirement_ids": [requirement_id], "status": "accepted"})
        lifelines.append({"id": f"lifeline-{actor_id}", "name": subject, "status": "accepted"})
        messages.append({"id": message_id, "name": str(requirement.get("statement", requirement.get("object", ""))), "from_id": f"lifeline-{actor_id}", "to_id": "lifeline-system", "sequence": 1, "requirement_ids": [requirement_id], "status": "accepted"})
        links.append({"source_id": requirement_id, "predicate": "refines", "target_id": use_case_id, "status": "accepted"})
    model: dict[str, object] = {
        "format": "ai4mbse/mbse",
        "version": 1,
        "status": "accepted",
        "review_history": [],
        "actors": sorted(_unique(actors), key=lambda item: str(item["id"])),
        "use_cases": sorted(_unique(use_cases), key=lambda item: str(item["id"])),
        "activities": sorted(_unique(activities), key=lambda item: str(item["id"])),
        "lifelines": sorted(_unique(lifelines), key=lambda item: str(item["id"])),
        "messages": sorted(_unique(messages), key=lambda item: str(item["id"])),
        "trace_links": sorted(links, key=lambda item: (str(item["source_id"]), str(item["target_id"]))),
    }
    model["revision"] = canonical_hash(model)
    result = _clone(state)
    result["mbse"] = model
    result["rflp"] = result.get("rflp")
    return result


def review_mbse_element(
    state: dict[str, object], element_id: str, decision: str
) -> dict[str, object]:
    """Review one generated MBSE semantic element."""

    if decision not in {"accepted", "rejected"}:
        raise ContractViolation("MBSE 确认结果必须是 accepted 或 rejected")
    result = _clone(state)
    model = result.get("mbse")
    if not isinstance(model, dict):
        raise ContractViolation("MBSE semantic model not generated")
    collections = ("actors", "use_cases", "activities", "lifelines", "messages")
    matches = [
        item
        for collection in collections
        for item in model.get(collection, ())
        if str(item.get("id", "")) == element_id
    ]
    if len(matches) != 1:
        raise ContractViolation("MBSE 审核对象不存在或不唯一")
    matches[0]["status"] = decision
    statuses = [
        item.get("status")
        for collection in collections
        for item in model.get(collection, ())
    ]
    model["status"] = "accepted" if statuses and all(status == "accepted" for status in statuses) else "review"
    return result


def confirm_mbse(state: dict[str, object]) -> dict[str, object]:
    """Confirm all remaining MBSE candidates after the human review action."""

    result = _clone(state)
    model = result.get("mbse")
    if not isinstance(model, dict):
        raise ContractViolation("MBSE semantic model not generated")
    use_cases = tuple(model.get("use_cases", ()))
    activities = tuple(model.get("activities", ()))
    if not use_cases or not activities:
        raise ContractViolation("MBSE 至少需要一个用例和一个活动")
    if any(item.get("status") == "rejected" for item in use_cases + activities):
        raise ContractViolation("MBSE 用例或活动已驳回，请先重新生成模型")
    for collection in ("actors", "use_cases", "activities", "lifelines", "messages"):
        for item in model.get(collection, ()):
            if item.get("status") != "rejected":
                item["status"] = "accepted"
    model["status"] = "accepted"
    history = list(model.get("review_history", ()))
    history.append({"decision": "accepted", "revision": model.get("revision", "")})
    model["review_history"] = history
    revision_payload = {key: value for key, value in model.items() if key not in {"revision", "review_history"}}
    model["revision"] = canonical_hash(revision_payload)
    return result


def apply_mbse_edit(
    state: dict[str, object], expected_revision: str, operation: dict[str, object]
) -> dict[str, object]:
    model = state.get("mbse") or {}
    if str(model.get("revision", "")) != str(expected_revision):
        raise ContractViolation("MBSE revision is stale; reload the current model")
    kind = str(operation.get("kind", ""))
    if kind not in {"rename", "set-status"}:
        raise ContractViolation("unsupported MBSE edit")
    target_id = str(operation.get("id", ""))
    result = _clone(state)
    model_copy = result["mbse"]
    collections = ("actors", "use_cases", "activities", "lifelines", "messages")
    matches = [
        item
        for collection in collections
        for item in model_copy.get(collection, ())
        if str(item.get("id", "")) == target_id
    ]
    if len(matches) != 1:
        raise ContractViolation("MBSE edit target not found or ambiguous")
    target = matches[0]
    if kind == "rename":
        name = str(operation.get("name", "")).strip()
        if not name:
            raise ContractViolation("MBSE name cannot be empty")
        target["name"] = name
        target["status"] = "accepted"
    else:
        status = str(operation.get("status", "")).strip()
        if status not in {"candidate", "accepted", "rejected"}:
            raise ContractViolation("invalid MBSE status")
        target["status"] = status
    statuses = [
        item.get("status")
        for collection in collections
        for item in model_copy.get(collection, ())
    ]
    model_copy["status"] = "accepted" if statuses and all(status == "accepted" for status in statuses) else "review"
    revision_payload = {key: value for key, value in model_copy.items() if key != "revision"}
    model_copy["revision"] = canonical_hash(revision_payload)
    result["baseline"] = None
    result["project"] = None
    result["rflp"] = None
    return result
