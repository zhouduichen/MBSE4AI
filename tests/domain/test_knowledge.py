from rflp_lite.application.knowledge_library import import_combat_scenarios, import_requirement_history


def test_requirement_history_json_is_versioned():
    records = import_requirement_history(
        [{"id": "h-1", "statement": "系统应记录状态"}],
        dataset_id="history",
        dataset_version="2026.1",
    )
    assert records[0].dataset_id == "history"
    assert records[0].dataset_version == "2026.1"


def test_combat_scenario_record_normalizes_steps():
    records = import_combat_scenarios(
        [{"id": "scenario-1", "title": "侦察", "steps": ["发现", "上报"]}],
        "combat",
        "2026.1",
    )
    assert records[0].steps == ("发现", "上报")
