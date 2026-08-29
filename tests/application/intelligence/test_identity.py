from rflp_lite.application.intelligence.identity import (
    advance_content_revision,
    ensure_entity_metadata,
    ensure_workbench_metadata,
    entity_match_keys,
    label_similarity,
)


def test_stakeholder_match_key_does_not_depend_on_input_hash() -> None:
    first = ensure_entity_metadata(
        "stakeholder",
        {"id": "st-1", "name": " 运维人员 ", "category": "operator"},
        editor="llm",
    )
    second = ensure_entity_metadata(
        "stakeholder",
        {"id": "st-2", "name": "运维人员", "category": "operator"},
        editor="llm",
    )

    assert entity_match_keys("stakeholder", first) == entity_match_keys(
        "stakeholder", second
    )
    assert first["match_keys"] == ["stakeholder:operator:运维人员"]
    assert label_similarity("系统运维人员", "运维人员") >= 0.95


def test_legacy_workbench_gets_lightweight_metadata_without_changing_ids() -> None:
    state = {
        "revision": 4,
        "stakeholders": [
            {"id": "st-1", "name": "管理员", "category": "operator"}
        ],
        "concerns": [],
        "needs": [],
        "claims": [],
        "structured_requirements": [],
        "scenarios": [],
    }

    migrated = ensure_workbench_metadata(state)

    assert migrated["stakeholders"][0]["id"] == "st-1"
    assert migrated["stakeholders"][0]["revision"] == 1
    assert migrated["stakeholders"][0]["field_sources"]["name"] == "rule"
    assert migrated["content_revision"] == 4
    assert migrated["deletion_registry"] == []


def test_missing_entity_id_is_derived_from_identity_not_source_item_id() -> None:
    first = ensure_entity_metadata(
        "stakeholder",
        {"id": "", "name": "运维人员", "category": "operator", "source_item_id": "a"},
        editor="llm",
    )
    second = ensure_entity_metadata(
        "stakeholder",
        {"name": "运维人员", "category": "operator", "source_item_id": "b"},
        editor="llm",
    )

    assert first["id"] == second["id"]
    assert str(first["id"]).startswith("stakeholder-")


def test_advance_content_revision_migrates_then_increments_once() -> None:
    advanced = advance_content_revision(
        {
            "revision": 9,
            "stakeholders": [],
            "concerns": [],
            "needs": [],
            "claims": [],
            "structured_requirements": [],
            "scenarios": [],
        }
    )

    assert advanced["revision"] == 9
    assert advanced["content_revision"] == 10
