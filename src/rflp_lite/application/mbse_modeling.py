"""Deterministic semantic Use Case, activity and sequence model generation."""

from __future__ import annotations

import json
from typing import Any

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.application.mbse_semantics import (
    generate_mbse_semantic_revision,
    mbse_entity_index,
)


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
    model_state = _clone(state)
    if model_state.get("use_case_drafts") and not model_state.get("scenarios"):
        model_state["scenarios"] = [
            {
                "id": draft.get("scenario_id", draft.get("id")),
                "title": draft.get("title", draft.get("name", "用例")),
                "actors": draft.get("actors", ()),
                "steps": [step.get("message", "") for step in draft.get("main_flow", ()) if isinstance(step, dict)],
                "interaction_steps": draft.get("main_flow", ()),
                "preconditions": draft.get("preconditions", ()),
                "expected_outcomes": draft.get("postconditions", ()),
                "requirement_ids": draft.get("requirement_ids", ()),
                "status": draft.get("status", "accepted"),
                "producer": draft.get("producer", "rule"),
            }
            for draft in model_state.get("use_case_drafts", ())
            if isinstance(draft, dict)
        ]
    model = generate_mbse_semantic_revision(
        model_state,
        provenance={
            "producer": "mbse-modeling",
            "accepted_requirement_ids": [str(item["id"]) for item in accepted],
        },
    )
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
    semantic = model.get("semantic_model")
    if isinstance(semantic, dict):
        entity = mbse_entity_index(semantic).get(element_id)
        if entity is not None:
            entity["status"] = decision
    statuses = [
        item.get("status")
        for collection in collections
        for item in model.get(collection, ())
    ]
    model["status"] = "accepted" if statuses and all(status == "accepted" for status in statuses) else "review"
    if isinstance(semantic, dict):
        semantic_statuses = [
            item.get("status")
            for item in mbse_entity_index(semantic).values()
            if item.get("kind") not in {"source_region", "environment"}
        ]
        if semantic_statuses and all(status == "accepted" for status in semantic_statuses):
            model["status"] = "accepted"
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
            if item.get("status") not in {"rejected", "needs-analysis"}:
                item["status"] = "accepted"
    semantic = model.get("semantic_model")
    if isinstance(semantic, dict):
        for item in mbse_entity_index(semantic).values():
            if item.get("status") not in {"rejected", "needs-analysis"}:
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
    if kind not in {"rename", "set-status", "update-fields"}:
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
    if kind == "update-fields":
        allowed = {
            "actors": {"name"},
            "use_cases": {"name", "preconditions", "postconditions", "requirement_ids"},
            "activities": {"name", "steps", "requirement_ids"},
            "messages": {"name", "message", "sort", "guard", "sender", "receiver", "sender_lifeline_id", "receiver_lifeline_id", "requirement_ids"},
            "lifelines": {"name", "requirement_ids"},
        }
        collection = next((name for name in collections if target in model_copy.get(name, ())), "")
        fields = operation.get("fields")
        if not isinstance(fields, dict) or not set(fields) <= allowed.get(collection, set()):
            raise ContractViolation("unsupported MBSE edit field")
        known_requirements = {str(item.get("id")) for item in result.get("structured_requirements", ()) if isinstance(item, dict)}
        if "requirement_ids" in fields and not set(str(value) for value in fields["requirement_ids"]) <= known_requirements:
            raise ContractViolation("MBSE edit references unknown requirement")
        for field, value in fields.items():
            target["name" if field == "message" else field] = value
        target["status"] = "stale"
        from rflp_lite.application.model_impact import impact_for_change, mark_impacted_stale
        result = mark_impacted_stale(result, impact_for_change(result, {target_id}))
        model_copy = result["mbse"]
        target = next(item for collection in collections for item in model_copy.get(collection, ()) if str(item.get("id")) == target_id)
    elif kind == "rename":
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
    semantic = model_copy.get("semantic_model")
    if isinstance(semantic, dict):
        semantic_target = mbse_entity_index(semantic).get(target_id)
        if semantic_target is not None:
            if kind == "rename":
                semantic_target["name"] = target["name"]
            semantic_target["status"] = target["status"]
    revision_payload = {key: value for key, value in model_copy.items() if key != "revision"}
    model_copy["revision"] = canonical_hash(revision_payload)
    result["baseline"] = None
    result["project"] = None
    result["rflp"] = None
    return result
