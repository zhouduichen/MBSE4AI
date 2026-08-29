import pytest

from rflp_lite.application.intelligence.reconciliation import (
    ReconcileSummary,
    accumulate_summary,
    reconcile_entities,
    reconcile_relations,
)
from rflp_lite.domain.errors import ContractViolation


def _state() -> dict[str, object]:
    return {
        "stakeholders": [
            {
                "id": "st-1",
                "name": "现场管理员",
                "category": "operator",
                "goals": ["稳定运行"],
                "aliases": ["管理员"],
                "match_keys": ["stakeholder:operator:管理员"],
                "field_sources": {"name": "user", "goals": "llm"},
                "revision": 2,
                "suggested_changes": [],
            }
        ],
        "deletion_registry": [],
    }


def test_reconcile_preserves_user_value_and_updates_machine_field() -> None:
    state, summary = reconcile_entities(
        _state(),
        "stakeholders",
        ({"name": "管理员", "category": "operator", "goals": ["安全运行"]},),
        block_id="stakeholders",
        input_hash="hash-2",
    )

    item = state["stakeholders"][0]
    assert item["name"] == "现场管理员"
    assert item["goals"] == ["安全运行"]
    assert item["suggested_changes"][0]["field"] == "name"
    assert summary.updated == 1


def test_reconcile_is_idempotent_and_respects_human_deletion() -> None:
    state = _state()
    incoming = ({"name": "管理员", "category": "operator", "goals": []},)
    once, _ = reconcile_entities(
        state,
        "stakeholders",
        incoming,
        block_id="stakeholders",
        input_hash="h",
    )
    twice, _ = reconcile_entities(
        once,
        "stakeholders",
        incoming,
        block_id="stakeholders",
        input_hash="h",
    )
    assert len(twice["stakeholders"]) == 1

    twice["stakeholders"] = []
    twice["deletion_registry"] = [
        {
            "entity_type": "stakeholder",
            "match_keys": ["stakeholder:operator:管理员"],
        }
    ]
    suppressed, summary = reconcile_entities(
        twice,
        "stakeholders",
        incoming,
        block_id="stakeholders",
        input_hash="h2",
    )
    assert suppressed["stakeholders"] == []
    assert suppressed["analysis_review_hints"][0]["operation"] == "upsert_entity"
    assert summary.suppressed == 1


def test_propose_change_never_overwrites_even_a_machine_field() -> None:
    state, summary = reconcile_entities(
        _state(),
        "stakeholders",
        (
            {
                "operation": "propose_change",
                "target_id": "st-1",
                "name": "现场管理员",
                "category": "operator",
                "goals": ["建议目标"],
            },
        ),
        block_id="stakeholders",
        input_hash="hash-3",
    )

    assert state["stakeholders"][0]["goals"] == ["稳定运行"]
    assert state["stakeholders"][0]["suggested_changes"][-1]["suggested"] == [
        "建议目标"
    ]
    assert summary.suggested == 1


def test_llm_conflict_with_explicit_rule_field_becomes_suggestion() -> None:
    state = _state()
    state["stakeholders"][0]["field_sources"]["name"] = "rule"
    reconciled, _ = reconcile_entities(
        state,
        "stakeholders",
        (
            {
                "operation": "enrich_fields",
                "target_id": "st-1",
                "name": "模型改名",
                "category": "operator",
            },
        ),
        block_id="stakeholders",
        input_hash="hash-4",
    )

    assert reconciled["stakeholders"][0]["name"] == "现场管理员"
    assert reconciled["stakeholders"][0]["suggested_changes"][-1]["suggested"] == "模型改名"


def test_unique_high_similarity_role_reuses_stable_id() -> None:
    state = {
        "stakeholders": [
            {
                "id": "st-operator",
                "name": "运维人员",
                "category": "operator",
                "field_sources": {"name": "rule"},
            }
        ],
        "deletion_registry": [],
    }
    reconciled, _ = reconcile_entities(
        state,
        "stakeholders",
        ({"name": "系统运维人员", "category": "operator"},),
        block_id="stakeholders",
        input_hash="hash-5",
    )

    assert [item["id"] for item in reconciled["stakeholders"]] == ["st-operator"]


def test_deleted_role_is_suppressed_through_conservative_similarity() -> None:
    state = {
        "stakeholders": [],
        "deletion_registry": [
            {
                "entity_type": "stakeholder",
                "match_keys": ["stakeholder:operator:运维人员"],
                "snapshot": {"name": "运维人员", "category": "operator"},
            }
        ],
    }
    reconciled, summary = reconcile_entities(
        state,
        "stakeholders",
        ({"name": "系统运维人员", "category": "operator"},),
        block_id="stakeholders",
        input_hash="hash-6",
    )

    assert reconciled["stakeholders"] == []
    assert summary.suppressed == 1


def test_entity_reconciliation_rejects_unknown_or_delete_operation() -> None:
    for operation in ("delete", "remove", "add_relation"):
        with pytest.raises(ContractViolation, match="operation"):
            reconcile_entities(
                _state(),
                "stakeholders",
                ({"operation": operation, "name": "管理员"},),
                block_id="stakeholders",
                input_hash="hash",
            )


def test_flag_for_review_adds_default_hint_without_changing_entity_fields() -> None:
    reconciled, summary = reconcile_entities(
        _state(),
        "stakeholders",
        ({"operation": "flag_for_review", "target_id": "st-1"},),
        block_id="stakeholders",
        input_hash="hash-review",
    )

    assert reconciled["stakeholders"][0]["name"] == "现场管理员"
    assert "人工复核" in reconciled["stakeholders"][0]["review_hint"]
    assert summary.updated == 1


def test_only_upsert_may_create_an_entity() -> None:
    reconciled, summary = reconcile_entities(
        {"stakeholders": [], "deletion_registry": []},
        "stakeholders",
        (
            {
                "operation": "enrich_fields",
                "name": "新角色",
                "category": "operator",
            },
        ),
        block_id="stakeholders",
        input_hash="hash-enrich",
    )

    assert reconciled["stakeholders"] == []
    assert reconciled["analysis_review_hints"][0]["operation"] == "enrich_fields"
    assert summary.added == 0
    assert summary.suggested == 1


def test_relation_reconciliation_is_idempotent_and_never_removes() -> None:
    state = {
        "stakeholders": [{"id": "st-1", "name": "管理员"}],
        "claims": [{"id": "req-1", "object": "系统应记录日志"}],
        "trace_links": [
            {
                "id": "rel-existing",
                "source_id": "st-1",
                "predicate": "hasNeed",
                "target_id": "req-1",
            }
        ],
        "deletion_registry": [],
    }
    incoming = (
        {
            "operation": "add_relation",
            "id": "model-rel-1",
            "source_id": "st-1",
            "predicate": "hasNeed",
            "target_id": "req-1",
        },
    )

    once, first_summary = reconcile_relations(
        state, incoming, block_id="architecture", input_hash="h1"
    )
    twice, second_summary = reconcile_relations(
        once, incoming, block_id="architecture", input_hash="h1"
    )

    assert [item["id"] for item in twice["trace_links"]] == ["rel-existing"]
    assert first_summary.related == 0
    assert second_summary.related == 0


def test_relation_reconciliation_adds_once_and_validates_endpoints() -> None:
    state = {
        "stakeholders": [{"id": "st-1", "name": "管理员"}],
        "claims": [{"id": "req-1", "object": "系统应记录日志"}],
        "trace_links": [],
        "deletion_registry": [],
    }
    incoming = (
        {
            "operation": "add_relation",
            "id": "model-rel-1",
            "source_id": "st-1",
            "predicate": "hasNeed",
            "target_id": "req-1",
        },
    )
    once, summary = reconcile_relations(
        state, incoming, block_id="architecture", input_hash="h1"
    )
    twice, repeated = reconcile_relations(
        once, incoming, block_id="architecture", input_hash="h1"
    )

    assert len(twice["trace_links"]) == 1
    assert twice["trace_links"][0]["source_item_id"] == "model-rel-1"
    assert summary.related == 1
    assert repeated.related == 0

    with pytest.raises(ContractViolation, match="endpoint"):
        reconcile_relations(
            state,
            (
                {
                    "operation": "add_relation",
                    "source_id": "missing",
                    "predicate": "hasNeed",
                    "target_id": "req-1",
                },
            ),
            block_id="architecture",
            input_hash="h2",
        )


def test_relation_flag_is_idempotent_and_delete_is_rejected() -> None:
    state = {
        "stakeholders": [{"id": "st-1", "name": "管理员"}],
        "claims": [{"id": "req-1", "object": "系统应记录日志"}],
        "trace_links": [
            {
                "id": "rel-1",
                "source_id": "st-1",
                "predicate": "hasNeed",
                "target_id": "req-1",
            }
        ],
        "deletion_registry": [],
    }
    flagged, summary = reconcile_relations(
        state,
        ({"operation": "flag_for_review", "id": "rel-1"},),
        block_id="architecture",
        input_hash="h-review",
    )
    repeated, second_summary = reconcile_relations(
        flagged,
        ({"operation": "flag_for_review", "id": "rel-1"},),
        block_id="architecture",
        input_hash="h-review",
    )

    assert len(repeated["trace_links"]) == 1
    assert "人工复核" in repeated["trace_links"][0]["review_hint"]
    assert summary.suggested == 1
    assert second_summary.suggested == 0

    with pytest.raises(ContractViolation, match="operation"):
        reconcile_relations(
            state,
            (
                {
                    "operation": "delete",
                    "source_id": "st-1",
                    "predicate": "hasNeed",
                    "target_id": "req-1",
                },
            ),
            block_id="architecture",
            input_hash="h-delete",
        )


def test_deleted_relation_is_suppressed_until_human_restore() -> None:
    match_key = "relation:st-1:hasNeed:req-1"
    state = {
        "stakeholders": [{"id": "st-1", "name": "管理员"}],
        "claims": [{"id": "req-1", "object": "系统应记录日志"}],
        "trace_links": [],
        "deletion_registry": [
            {"entity_type": "relation", "match_keys": [match_key]}
        ],
    }

    reconciled, summary = reconcile_relations(
        state,
        (
            {
                "operation": "add_relation",
                "source_id": "st-1",
                "predicate": "hasNeed",
                "target_id": "req-1",
            },
        ),
        block_id="architecture",
        input_hash="h-suppressed",
    )

    assert reconciled["trace_links"] == []
    assert reconciled["analysis_review_hints"][0]["match_keys"] == [match_key]
    assert summary.suppressed == 1


def test_summary_accumulates_without_mutating_state() -> None:
    state = {"analysis_summary": {"added": 2, "updated": 1}}

    result = accumulate_summary(
        state, ReconcileSummary(added=1, related=3, suppressed=1)
    )

    assert result == {
        "added": 3,
        "updated": 1,
        "related": 3,
        "suggested": 0,
        "suppressed": 1,
    }
    assert state == {"analysis_summary": {"added": 2, "updated": 1}}
