from rflp_lite.application.knowledge_retrieval import retrieve_requirements, retrieve_scenarios
from rflp_lite.application.knowledge_library import import_combat_scenarios, import_requirement_history


def test_requirement_retrieval_ranks_same_object_and_unit_first():
    records = import_requirement_history([
        {"id": "history-speed", "statement": "系统巡航速度不低于120 km/h", "attributes": [["巡航速度", "120 km/h"]]},
        {"id": "history-other", "statement": "系统应记录状态"},
    ], "history", "2026.1")
    matches = retrieve_requirements({"statement": "系统巡航速度不低于120 km/h", "attributes": [("巡航速度", "120 km/h")]}, records, limit=2)
    assert matches[0].record_id == "history-speed"
    assert "巡航速度" in matches[0].matched_terms


def test_scenario_ties_are_broken_by_record_id():
    records = import_combat_scenarios([
        {"id": "scenario-b", "title": "执行任务", "steps": ["提交任务"]},
        {"id": "scenario-a", "title": "执行任务", "steps": ["提交任务"]},
    ], "combat", "2026.1")
    first = retrieve_scenarios([{"id": "req-1", "statement": "执行任务"}], reversed(records), limit=5)
    second = retrieve_scenarios([{"id": "req-1", "statement": "执行任务"}], records, limit=5)
    assert first == second
