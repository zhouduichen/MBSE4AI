from __future__ import annotations

import json

import pytest

from rflp_lite.application.entity_deletion import (
    delete_entity,
    preview_entity_deletion,
    restore_entity,
)
from rflp_lite.application.intelligence.identity import ensure_entity_metadata
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


def _entity(entity_type: str, **values: object) -> dict[str, object]:
    return ensure_entity_metadata(entity_type, values)


def linked_stakeholder_state() -> dict[str, object]:
    stakeholder = _entity(
        "stakeholder",
        id="st-1",
        name="操作员",
        category="operator",
        producer="llm",
        last_editor="llm",
    )
    machine_concern = _entity(
        "concern",
        id="concern-1",
        name="安全运行",
        stakeholder_id="st-1",
        producer="llm",
        last_editor="llm",
    )
    human_concern = _entity(
        "concern",
        id="concern-user",
        name="人工关注点",
        stakeholder_id="st-1",
        producer="llm",
        last_editor="user",
    )
    machine_need = _entity(
        "need",
        id="need-1",
        name="安全启动",
        statement="操作员需要安全启动",
        stakeholder_id="st-1",
        concern_id="concern-1",
        producer="llm",
        last_editor="llm",
    )
    human_need = _entity(
        "need",
        id="need-user",
        name="人工需要",
        statement="操作员需要查看人工说明",
        stakeholder_id="st-1",
        concern_id="concern-user",
        producer="llm",
        last_editor="user",
    )
    scenario = _entity(
        "scenario",
        id="scenario-1",
        title="操作员启动",
        scenario_type="normal",
        actors=["操作员", "系统"],
        stakeholder_ids=["st-1"],
        requirement_ids=["req-1"],
        producer="llm",
        last_editor="llm",
    )
    return {
        "revision": 5,
        "content_revision": 7,
        "stakeholders": [stakeholder],
        "concerns": [machine_concern, human_concern],
        "needs": [machine_need, human_need],
        "claims": [
            _entity(
                "requirement",
                id="req-1",
                object="系统应记录启动结果",
                statement="系统应记录启动结果",
                producer="rule",
            )
        ],
        "structured_requirements": [
            _entity(
                "requirement",
                id="req-1",
                statement="系统应记录启动结果",
                producer="rule",
            )
        ],
        "scenarios": [scenario],
        "trace_links": [
            {
                "id": "trace-st-concern",
                "source_id": "st-1",
                "predicate": "hasConcern",
                "target_id": "concern-1",
            },
            {
                "id": "trace-concern-need",
                "source_id": "concern-1",
                "predicate": "motivates",
                "target_id": "need-1",
            },
            {
                "id": "trace-scenario-requirement",
                "source_id": "scenario-1",
                "predicate": "verifies",
                "target_id": "req-1",
            },
        ],
        "deletion_registry": [],
        "rflp": {"elements": []},
        "mbse": {"actors": []},
        "baseline": {"id": "baseline-1"},
        "coverage": {"ratio": 1.0},
        "analysis_coverage": {"status": "complete"},
        "svg": "<svg></svg>",
        "draft_graph": {"items": []},
    }


def test_delete_preview_lists_dependencies_without_mutating_state() -> None:
    state = linked_stakeholder_state()
    before = canonical_json(state)

    preview = preview_entity_deletion(state, "stakeholder", "st-1")

    assert preview["target"]["id"] == "st-1"
    assert preview["affected"]["concern_ids"] == ["concern-1", "concern-user"]
    assert preview["affected"]["need_ids"] == ["need-1", "need-user"]
    assert preview["affected"]["scenario_ids"] == ["scenario-1"]
    assert preview["affected"]["relation_ids"] == [
        "trace-concern-need",
        "trace-st-concern",
    ]
    assert preview["plan_hash"]
    assert canonical_json(state) == before


def test_human_delete_creates_recoverable_suppression_record() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "stakeholder", "st-1")

    deleted = delete_entity(
        state, "stakeholder", "st-1", str(preview["plan_hash"])
    )

    assert deleted["stakeholders"] == []
    assert [item["id"] for item in deleted["concerns"]] == ["concern-user"]
    assert [item["id"] for item in deleted["needs"]] == ["need-user"]
    assert deleted["concerns"][0]["stakeholder_id"] == ""
    assert deleted["needs"][0]["stakeholder_id"] == ""
    assert (
        deleted["concerns"][0]["review_hint"]
        == "原利益相关方已由人工删除，请重新关联"
    )
    assert deleted["scenarios"][0]["actors"] == ["系统"]
    assert deleted["scenarios"][0]["stakeholder_ids"] == []
    assert [item["id"] for item in deleted["trace_links"]] == [
        "trace-scenario-requirement"
    ]
    assert deleted["content_revision"] == 8
    assert state["content_revision"] == 7
    registry = deleted["deletion_registry"][0]
    assert registry["entity_id"] == "st-1"
    assert registry["entity_type"] == "stakeholder"
    assert registry["deleted_by"] == "user"
    assert registry["match_keys"] == preview["target"]["match_keys"]
    assert registry["recovery"]["removed_snapshots"]["concerns"][0]["id"] == "concern-1"
    assert deleted["rflp"] is None
    assert deleted["mbse"] is None
    assert deleted["baseline"] is None
    assert deleted["coverage"] == {}
    assert deleted["analysis_coverage"] == {}
    assert deleted["svg"] == ""
    assert deleted["draft_graph"] is None


def test_delete_rejects_a_stale_preview_hash() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "stakeholder", "st-1")
    changed = json.loads(canonical_json(state))
    changed["needs"].append(
        _entity(
            "need",
            id="need-late",
            statement="操作员需要新增能力",
            stakeholder_id="st-1",
            producer="llm",
        )
    )

    with pytest.raises(ContractViolation, match="删除影响已经变化，请重新预览"):
        delete_entity(changed, "stakeholder", "st-1", str(preview["plan_hash"]))


def test_restore_recovers_removed_objects_and_detached_references() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "stakeholder", "st-1")
    deleted = delete_entity(
        state, "stakeholder", "st-1", str(preview["plan_hash"])
    )

    restored = restore_entity(deleted, "stakeholder", "st-1")

    assert [item["id"] for item in restored["stakeholders"]] == ["st-1"]
    assert {item["id"] for item in restored["concerns"]} == {
        "concern-1",
        "concern-user",
    }
    assert {item["id"] for item in restored["needs"]} == {"need-1", "need-user"}
    restored_human = next(
        item for item in restored["needs"] if item["id"] == "need-user"
    )
    assert restored_human["stakeholder_id"] == "st-1"
    assert restored_human["review_hint"] == ""
    assert restored["scenarios"][0]["actors"] == ["操作员", "系统"]
    assert restored["scenarios"][0]["stakeholder_ids"] == ["st-1"]
    assert {item["id"] for item in restored["trace_links"]} == {
        "trace-st-concern",
        "trace-concern-need",
        "trace-scenario-requirement",
    }
    assert restored["deletion_registry"] == []
    assert restored["content_revision"] == 9


def test_requirement_delete_and_restore_detaches_scenario_reference() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "requirement", "req-1")

    deleted = delete_entity(
        state, "requirement", "req-1", str(preview["plan_hash"])
    )

    assert deleted["claims"] == []
    assert deleted["structured_requirements"] == []
    assert deleted["scenarios"][0]["requirement_ids"] == []
    assert deleted["trace_links"][:2] == state["trace_links"][:2]
    assert len(deleted["trace_links"]) == 2

    restored = restore_entity(deleted, "requirement", "req-1")
    assert restored["claims"][0]["id"] == "req-1"
    assert restored["structured_requirements"][0]["id"] == "req-1"
    assert restored["scenarios"][0]["requirement_ids"] == ["req-1"]
    assert any(item["id"] == "trace-scenario-requirement" for item in restored["trace_links"])


def test_scenario_delete_and_restore_only_changes_scenario_and_its_relations() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "scenario", "scenario-1")

    deleted = delete_entity(
        state, "scenario", "scenario-1", str(preview["plan_hash"])
    )

    assert deleted["scenarios"] == []
    assert [
        (item["id"], item["name"], item["category"])
        for item in deleted["stakeholders"]
    ] == [("st-1", "操作员", "operator")]
    assert {item["id"] for item in deleted["trace_links"]} == {
        "trace-st-concern",
        "trace-concern-need",
    }
    restored = restore_entity(deleted, "scenario", "scenario-1")
    assert restored["scenarios"][0]["id"] == "scenario-1"
    assert any(item["id"] == "trace-scenario-requirement" for item in restored["trace_links"])


def test_restore_is_idempotent_after_registry_entry_is_removed() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "scenario", "scenario-1")
    deleted = delete_entity(
        state, "scenario", "scenario-1", str(preview["plan_hash"])
    )
    restored = restore_entity(deleted, "scenario", "scenario-1")

    again = restore_entity(restored, "scenario", "scenario-1")

    assert again == restored
    assert again["content_revision"] == restored["content_revision"]


def test_restore_merges_same_match_key_without_overwriting_user_fields() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "stakeholder", "st-1")
    deleted = delete_entity(
        state, "stakeholder", "st-1", str(preview["plan_hash"])
    )
    replacement = _entity(
        "stakeholder",
        id="st-replacement",
        name="人工操作员名称",
        aliases=["操作员"],
        category="operator",
        producer="user",
        last_editor="user",
    )
    replacement["field_sources"]["name"] = "user"
    deleted["stakeholders"] = [replacement]

    restored = restore_entity(deleted, "stakeholder", "st-1")

    assert len(restored["stakeholders"]) == 1
    assert restored["stakeholders"][0]["id"] == "st-replacement"
    assert restored["stakeholders"][0]["name"] == "人工操作员名称"
    assert restored["deletion_registry"] == []


@pytest.mark.parametrize("entity_type", ["concern", "need", "architecture"])
def test_preview_rejects_unsupported_direct_delete_types(entity_type: str) -> None:
    with pytest.raises(ContractViolation, match="不支持删除该对象类型"):
        preview_entity_deletion(linked_stakeholder_state(), entity_type, "unknown")


def test_preview_and_restore_reject_missing_objects() -> None:
    state = linked_stakeholder_state()
    with pytest.raises(ContractViolation, match="待删除对象不存在"):
        preview_entity_deletion(state, "scenario", "missing")
    with pytest.raises(ContractViolation, match="已删除对象不存在"):
        restore_entity(state, "scenario", "missing")
