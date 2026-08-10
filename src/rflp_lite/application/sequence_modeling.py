"""Build standard interaction semantics from reviewed scenarios."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.sequence import (
    SEQUENCE_FORMAT,
    SEQUENCE_VERSION,
    validate_sequence_interaction,
)


_MESSAGE_PATTERN = re.compile(
    r"^\s*(?P<sender>.+?)\s*(?:->|→)\s*(?P<receiver>.+?)\s*[:：]\s*(?P<message>.+?)\s*$"
)


def _scenario(state: Mapping[str, object], scenario_id: str) -> Mapping[str, object]:
    for item in state.get("scenarios", ()):
        if isinstance(item, Mapping) and str(item.get("id")) == scenario_id:
            if str(item.get("status")) != "accepted":
                raise ContractViolation("场景尚未确认，确认后才能生成顺序图")
            return item
    raise ContractViolation("场景不存在")


def _names(scenario: Mapping[str, object]) -> list[str]:
    names: list[str] = []
    raw_actors = scenario.get("actors", ())
    if isinstance(raw_actors, (str, bytes)):
        raw_actors = (raw_actors,)
    for value in raw_actors:
        name = str(value).strip()
        if name and name not in names:
            names.append(name)
    if not names:
        names.append("使用者")
    if "系统" not in names:
        names.append("系统")
    return names


def _lifeline_id(name: str) -> str:
    return f"lifeline-{canonical_hash((name,))[:12]}"


def _build_lifelines(scenario: Mapping[str, object]) -> list[dict[str, object]]:
    result = []
    for name in _names(scenario):
        result.append(
            {
                "id": _lifeline_id(name),
                "name": name,
                "kind": "system" if name == "系统" else "actor",
                "classifier_id": None,
                "requirement_ids": list(scenario.get("requirement_ids", ())),
            }
        )
    return result


def _ensure_lifeline(
    lifelines: list[dict[str, object]], name: str, scenario: Mapping[str, object]
) -> str:
    clean = name.strip() or "系统"
    identifier = _lifeline_id(clean)
    if not any(item["id"] == identifier for item in lifelines):
        lifelines.append(
            {
                "id": identifier,
                "name": clean,
                "kind": "system" if clean == "系统" else "block",
                "classifier_id": None,
                "requirement_ids": list(scenario.get("requirement_ids", ())),
            }
        )
    return identifier


def _raw_steps(scenario: Mapping[str, object]) -> tuple[object, ...]:
    value = scenario.get("interaction_steps") or scenario.get("steps", ())
    if isinstance(value, str):
        return tuple(item.strip() for item in value.splitlines() if item.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return ()


def _step_record(
    raw: object,
    index: int,
    lifelines: list[dict[str, object]],
    scenario: Mapping[str, object],
) -> dict[str, object]:
    if isinstance(raw, Mapping):
        sender = str(raw.get("sender", "")).strip()
        receiver = str(raw.get("receiver", "")).strip()
        message = str(raw.get("message", raw.get("name", ""))).strip()
        explicit = bool(sender and receiver and message)
        sort = str(raw.get("sort", "sync_call"))
        guard = raw.get("guard")
        requirement_ids = list(raw.get("requirement_ids", scenario.get("requirement_ids", ())))
    else:
        text = str(raw).strip()
        match = _MESSAGE_PATTERN.match(text)
        if match:
            sender = match.group("sender").strip()
            receiver = match.group("receiver").strip()
            message = match.group("message").strip()
            explicit = True
        else:
            actors = _names(scenario)
            sender = actors[0]
            receiver = "系统"
            message = text or f"步骤 {index}"
            explicit = False
        sort = "sync_call"
        guard = None
        requirement_ids = list(scenario.get("requirement_ids", ()))
    sender_id = _ensure_lifeline(lifelines, sender, scenario)
    receiver_id = _ensure_lifeline(lifelines, receiver, scenario)
    return {
        "order": index,
        "sender": sender,
        "receiver": receiver,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "message": message or f"步骤 {index}",
        "sort": sort,
        "guard": None if guard in (None, "") else str(guard),
        "requirement_ids": requirement_ids,
        "status": "accepted" if explicit else "candidate",
    }


def _build_content(
    scenario: Mapping[str, object],
    lifelines: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    messages: list[dict[str, object]] = []
    occurrences: list[dict[str, object]] = []
    fragments: list[dict[str, object]] = []
    executions: list[dict[str, object]] = []
    for index, raw in enumerate(_raw_steps(scenario), start=1):
        record = _step_record(raw, index, lifelines, scenario)
        digest = canonical_hash((scenario["id"], index, record["sender"], record["receiver"], record["message"], record["sort"]))[:12]
        message_id = f"message-{digest}"
        send_id = f"occurrence-send-{digest}"
        receive_id = f"occurrence-receive-{digest}"
        messages.append(
            {
                "id": message_id,
                "name": record["message"],
                "sort": record["sort"],
                "sender_lifeline_id": record["sender_id"],
                "receiver_lifeline_id": record["receiver_id"],
                "send_occurrence_id": send_id,
                "receive_occurrence_id": receive_id,
                "arguments": [],
                "guard": record["guard"],
                "requirement_ids": record["requirement_ids"],
                "status": record["status"],
            }
        )
        occurrences.extend(
            [
                {"id": send_id, "kind": "send", "lifeline_id": record["sender_id"], "message_id": message_id, "order": index},
                {"id": receive_id, "kind": "receive", "lifeline_id": record["receiver_id"], "message_id": message_id, "order": index},
            ]
        )
        fragments.append({"id": f"fragment-{digest}", "kind": "message", "message_id": message_id, "order": index})
        if record["sort"] != "reply":
            start_id = f"occurrence-execution-start-{digest}"
            finish_id = f"occurrence-execution-finish-{digest}"
            occurrences.extend(
                [
                    {"id": start_id, "kind": "execution_start", "lifeline_id": record["receiver_id"], "message_id": message_id, "order": index},
                    {"id": finish_id, "kind": "execution_finish", "lifeline_id": record["receiver_id"], "message_id": message_id, "order": index},
                ]
            )
            executions.append(
                {
                    "id": f"execution-{digest}",
                    "lifeline_id": record["receiver_id"],
                    "start_occurrence_id": start_id,
                    "finish_occurrence_id": finish_id,
                    "operation": record["message"],
                    "depth": 0,
                }
            )
    return messages, occurrences, fragments, executions


def _trace_links(scenario: Mapping[str, object], interaction_id: str) -> list[dict[str, object]]:
    return [
        {"id": f"trace-{canonical_hash((requirement_id, interaction_id))[:12]}", "source_id": str(requirement_id), "predicate": "refines", "target_id": interaction_id, "status": "candidate"}
        for requirement_id in scenario.get("requirement_ids", ())
    ]


def build_sequence_interaction(state: dict[str, object], scenario_id: str) -> dict[str, object]:
    scenario = _scenario(state, scenario_id)
    interaction_id = f"interaction-{canonical_hash((scenario_id, scenario.get('revision', 1), scenario.get('hash', '')))[:12]}"
    lifelines = _build_lifelines(scenario)
    messages, occurrences, fragments, executions = _build_content(scenario, lifelines)
    status = "ready" if messages and all(item["status"] == "accepted" for item in messages) else "candidate"
    return validate_sequence_interaction(
        {
            "format": SEQUENCE_FORMAT,
            "version": SEQUENCE_VERSION,
            "id": interaction_id,
            "name": str(scenario.get("title", "未命名场景")),
            "source_scenario_id": scenario_id,
            "source_scenario_revision": int(scenario.get("revision", 1)),
            "source_scenario_hash": str(scenario.get("hash", "")),
            "lifelines": lifelines,
            "messages": messages,
            "occurrences": occurrences,
            "executions": executions,
            "fragments": fragments,
            "combined_fragments": [],
            "operands": [],
            "trace_links": _trace_links(scenario, interaction_id),
            "status": status,
        }
    )


def _legacy_lifeline_id(item: Mapping[str, object], index: int) -> str:
    value = str(item.get("id", "")).strip()
    return value or f"lifeline-legacy-{index}"


def _legacy_model_to_interaction(model: Mapping[str, object]) -> dict[str, object]:
    """Adapt the pre-interaction MBSE model without coupling the renderer to it."""

    source_lifelines = [
        item for item in model.get("lifelines", ()) if isinstance(item, Mapping)
    ]
    lifelines: list[dict[str, object]] = []
    lifeline_ids: set[str] = set()
    for index, item in enumerate(source_lifelines, start=1):
        item_id = _legacy_lifeline_id(item, index)
        if item_id in lifeline_ids:
            continue
        lifeline_ids.add(item_id)
        lifelines.append(
            {
                "id": item_id,
                "name": str(item.get("name", item_id)),
                "kind": str(item.get("kind", "actor")),
                "classifier_id": item.get("classifier_id"),
                "requirement_ids": list(item.get("requirement_ids", ())),
            }
        )
    if not lifelines:
        raise ContractViolation("legacy MBSE model has no lifelines")

    source_messages = [
        item for item in model.get("messages", ()) if isinstance(item, Mapping)
    ]
    source_messages.sort(key=lambda item: (int(item.get("sequence", 0)), str(item.get("id", ""))))
    messages: list[dict[str, object]] = []
    occurrences: list[dict[str, object]] = []
    executions: list[dict[str, object]] = []
    fragments: list[dict[str, object]] = []
    fallback_sender = lifelines[0]["id"]
    fallback_receiver = lifelines[-1]["id"]
    for index, item in enumerate(source_messages, start=1):
        sender_id = str(item.get("sender_lifeline_id", item.get("from_id", fallback_sender)))
        receiver_id = str(item.get("receiver_lifeline_id", item.get("to_id", fallback_receiver)))
        if sender_id not in lifeline_ids:
            sender_id = str(fallback_sender)
        if receiver_id not in lifeline_ids:
            receiver_id = str(fallback_receiver)
        digest = canonical_hash(("legacy", item.get("id", index), index))[:12]
        message_id = f"message-legacy-{digest}"
        send_id = f"occurrence-send-{digest}"
        receive_id = f"occurrence-receive-{digest}"
        sort = str(item.get("sort", "sync_call"))
        if sort not in {"sync_call", "async_call", "reply", "create", "delete"}:
            sort = "sync_call"
        status = str(item.get("status", "candidate"))
        if status not in {"candidate", "accepted", "ready", "stale", "invalid"}:
            status = "candidate"
        messages.append(
            {
                "id": message_id,
                "name": str(item.get("name", "未命名消息")),
                "sort": sort,
                "sender_lifeline_id": sender_id,
                "receiver_lifeline_id": receiver_id,
                "send_occurrence_id": send_id,
                "receive_occurrence_id": receive_id,
                "arguments": list(item.get("arguments", ())),
                "guard": item.get("guard"),
                "requirement_ids": list(item.get("requirement_ids", ())),
                "status": status,
            }
        )
        occurrences.extend(
            [
                {"id": send_id, "kind": "send", "lifeline_id": sender_id, "message_id": message_id, "order": index},
                {"id": receive_id, "kind": "receive", "lifeline_id": receiver_id, "message_id": message_id, "order": index},
            ]
        )
        fragments.append({"id": f"fragment-{digest}", "kind": "message", "message_id": message_id, "order": index})
        if sort != "reply":
            start_id = f"occurrence-execution-start-{digest}"
            finish_id = f"occurrence-execution-finish-{digest}"
            occurrences.extend(
                [
                    {"id": start_id, "kind": "execution_start", "lifeline_id": receiver_id, "message_id": message_id, "order": index},
                    {"id": finish_id, "kind": "execution_finish", "lifeline_id": receiver_id, "message_id": message_id, "order": index},
                ]
            )
            executions.append(
                {
                    "id": f"execution-{digest}",
                    "lifeline_id": receiver_id,
                    "start_occurrence_id": start_id,
                    "finish_occurrence_id": finish_id,
                    "operation": str(item.get("name", "")),
                    "depth": 0,
                }
            )
    interaction_id = f"interaction-legacy-{canonical_hash(model)[:12]}"
    interaction_status = "ready" if messages and all(item["status"] == "accepted" for item in messages) else "candidate"
    return validate_sequence_interaction(
        {
            "format": SEQUENCE_FORMAT,
            "version": SEQUENCE_VERSION,
            "id": interaction_id,
            "name": str(model.get("name", "MBSE Sequence Interaction")),
            "source_scenario_id": model.get("source_scenario_id"),
            "source_scenario_revision": model.get("source_scenario_revision"),
            "source_scenario_hash": model.get("source_scenario_hash"),
            "lifelines": lifelines,
            "messages": messages,
            "occurrences": occurrences,
            "executions": executions,
            "fragments": fragments,
            "combined_fragments": [],
            "operands": [],
            "trace_links": list(model.get("trace_links", ())),
            "status": interaction_status,
        }
    )
