"""UML-style interaction contracts for deterministic sequence diagrams."""

from __future__ import annotations

import json
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


SEQUENCE_FORMAT = "ai4mbse/sequence-interaction"
SEQUENCE_VERSION = 1
MESSAGE_SORTS = frozenset({"sync_call", "async_call", "reply", "create", "delete"})
OPERATORS = frozenset({"alt", "opt", "loop", "par"})
ITEM_STATUSES = frozenset({"candidate", "accepted", "ready", "stale", "invalid"})


def _copy(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ContractViolation("sequence interaction must be an object")
    return json.loads(canonical_json(dict(value)))


def _collection(result: dict[str, object], key: str) -> list[dict[str, object]]:
    value = result.get(key, [])
    if not isinstance(value, list):
        raise ContractViolation(f"sequence {key} must be an array")
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ContractViolation(f"sequence {key} items must be objects")
        item_id = str(item.get("id", ""))
        if not item_id:
            raise ContractViolation(f"sequence {key} items require IDs")
        normalized.append(item)
    ids = [str(item["id"]) for item in normalized]
    if len(ids) != len(set(ids)):
        raise ContractViolation(f"sequence {key} IDs must be unique")
    result[key] = normalized
    return normalized


def _status(value: object, label: str, allowed: frozenset[str] = ITEM_STATUSES) -> str:
    status = str(value or "candidate")
    if status not in allowed:
        raise ContractViolation(f"invalid {label} status")
    return status


def message_sort_style(sort: str) -> str:
    styles = {
        "sync_call": "sync-call",
        "async_call": "async-call",
        "reply": "reply",
        "create": "create",
        "delete": "delete",
    }
    try:
        return styles[sort]
    except KeyError as exc:
        raise ContractViolation(f"unsupported message sort: {sort}") from exc


def validate_sequence_interaction(value: object) -> dict[str, object]:
    result = _copy(value)
    if result.get("format", SEQUENCE_FORMAT) != SEQUENCE_FORMAT:
        raise ContractViolation("unsupported sequence interaction format")
    if int(result.get("version", SEQUENCE_VERSION)) != SEQUENCE_VERSION:
        raise ContractViolation("unsupported sequence interaction version")
    result["format"] = SEQUENCE_FORMAT
    result["version"] = SEQUENCE_VERSION

    collections = {
        key: _collection(result, key)
        for key in (
            "lifelines",
            "messages",
            "occurrences",
            "executions",
            "fragments",
            "combined_fragments",
            "operands",
            "trace_links",
        )
    }
    lifeline_ids = {str(item["id"]) for item in collections["lifelines"]}
    message_ids = {str(item["id"]) for item in collections["messages"]}
    occurrence_ids = {str(item["id"]) for item in collections["occurrences"]}
    fragment_ids = {str(item["id"]) for item in collections["fragments"]}
    combined_ids = {str(item["id"]) for item in collections["combined_fragments"]}
    operand_ids = {str(item["id"]) for item in collections["operands"]}

    for item in collections["messages"]:
        sort = str(item.get("sort", "sync_call"))
        if sort not in MESSAGE_SORTS:
            raise ContractViolation(f"unsupported message sort: {sort}")
        for key in ("sender_lifeline_id", "receiver_lifeline_id"):
            if str(item.get(key, "")) not in lifeline_ids:
                raise ContractViolation(f"message {key} reference is invalid")
        for key in ("send_occurrence_id", "receive_occurrence_id"):
            if str(item.get(key, "")) not in occurrence_ids:
                raise ContractViolation(f"message {key} reference is invalid")
        item["sort"] = sort
        item["status"] = _status(item.get("status"), "message")
        item.setdefault("arguments", [])
        item.setdefault("requirement_ids", [])

    for item in collections["occurrences"]:
        if str(item.get("lifeline_id", "")) not in lifeline_ids:
            raise ContractViolation("occurrence lifeline_id reference is invalid")
        if str(item.get("message_id", "")) not in message_ids:
            raise ContractViolation("occurrence message_id reference is invalid")

    for item in collections["executions"]:
        if str(item.get("lifeline_id", "")) not in lifeline_ids:
            raise ContractViolation("execution lifeline_id reference is invalid")
        for key in ("start_occurrence_id", "finish_occurrence_id"):
            if str(item.get(key, "")) not in occurrence_ids:
                raise ContractViolation(f"execution {key} reference is invalid")

    for item in collections["fragments"]:
        kind = str(item.get("kind", "message"))
        if kind == "message" and str(item.get("message_id", "")) not in message_ids:
            raise ContractViolation("message fragment reference is invalid")
        if kind == "combined" and str(item.get("combined_fragment_id", "")) not in combined_ids:
            raise ContractViolation("combined fragment reference is invalid")
        if kind not in {"message", "combined"}:
            raise ContractViolation(f"unsupported interaction fragment: {kind}")

    for item in collections["combined_fragments"]:
        operator = str(item.get("operator", ""))
        if operator not in OPERATORS:
            raise ContractViolation(f"unsupported combined operator: {operator}")
        for operand_id in item.get("operand_ids", []):
            if str(operand_id) not in operand_ids:
                raise ContractViolation("combined fragment operand reference is invalid")

    for item in collections["operands"]:
        for fragment_id in item.get("fragment_ids", []):
            if str(fragment_id) not in fragment_ids:
                raise ContractViolation("operand fragment reference is invalid")

    result["status"] = _status(result.get("status"), "interaction")
    result.setdefault("name", "未命名交互")
    return result
