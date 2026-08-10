from __future__ import annotations

import pytest

from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.sequence import message_sort_style, validate_sequence_interaction


def valid_interaction_fixture() -> dict[str, object]:
    return {
        "format": "ai4mbse/sequence-interaction",
        "version": 1,
        "id": "interaction-1",
        "name": "登录",
        "source_scenario_id": "scenario-1",
        "source_scenario_revision": 1,
        "source_scenario_hash": "hash-1",
        "lifelines": [
            {"id": "user", "name": "用户", "kind": "actor"},
            {"id": "system", "name": "系统", "kind": "system"},
        ],
        "messages": [
            {
                "id": "message-1",
                "name": "登录请求",
                "sort": "sync_call",
                "sender_lifeline_id": "user",
                "receiver_lifeline_id": "system",
                "send_occurrence_id": "send-1",
                "receive_occurrence_id": "receive-1",
                "arguments": [],
                "guard": None,
                "requirement_ids": [],
                "status": "accepted",
            }
        ],
        "occurrences": [
            {"id": "send-1", "kind": "send", "lifeline_id": "user", "message_id": "message-1", "order": 1},
            {"id": "receive-1", "kind": "receive", "lifeline_id": "system", "message_id": "message-1", "order": 1},
        ],
        "executions": [],
        "fragments": [{"id": "fragment-1", "kind": "message", "message_id": "message-1", "order": 1}],
        "combined_fragments": [],
        "operands": [],
        "trace_links": [],
        "status": "ready",
    }


def test_validate_sequence_interaction_accepts_core_message_contract():
    result = validate_sequence_interaction(valid_interaction_fixture())
    assert result["format"] == "ai4mbse/sequence-interaction"
    assert result["version"] == 1


def test_validate_sequence_interaction_rejects_missing_lifeline_reference():
    model = valid_interaction_fixture()
    model["messages"][0]["receiver_lifeline_id"] = "lifeline-missing"
    with pytest.raises(ContractViolation, match="receiver_lifeline_id"):
        validate_sequence_interaction(model)


def test_validate_sequence_interaction_rejects_duplicate_ids():
    model = valid_interaction_fixture()
    model["lifelines"].append(dict(model["lifelines"][0]))
    with pytest.raises(ContractViolation, match="IDs must be unique"):
        validate_sequence_interaction(model)


def test_message_sort_style_uses_standard_styles():
    assert message_sort_style("sync_call") == "sync-call"
    assert message_sort_style("async_call") == "async-call"
    assert message_sort_style("reply") == "reply"
    assert message_sort_style("create") == "create"
    assert message_sort_style("delete") == "delete"
    with pytest.raises(ContractViolation, match="message sort"):
        message_sort_style("unknown")
