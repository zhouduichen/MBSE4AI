from rflp_lite.application.intelligence.coverage_audit import evaluate_project_coverage


def test_coverage_reports_missing_stakeholder_details_and_scenario_types() -> None:
    state = {
        "stakeholders": [
            {
                "id": "st-1",
                "name": "用户",
                "category": "end_user",
                "goals": [],
                "interactions": [],
            }
        ],
        "concerns": [],
        "needs": [],
        "claims": [
            {"id": "req-1", "status": "accepted", "object": "系统应支持操作"}
        ],
        "structured_requirements": [],
        "scenarios": [{"id": "sc-1", "scenario_type": "normal", "requirement_ids": ["req-1"]}],
    }
    report = evaluate_project_coverage(state, {})
    assert "stakeholder_goals" in report["missing_dimensions"]
    assert set(report["missing_scenario_types"]) == {
        "boundary",
        "failure",
        "recovery",
        "misuse",
    }
    assert "cybersecurity" in report["missing_scenario_dimensions"]
    assert report["stakeholder_ids_without_concerns"] == ["st-1"]
    assert report["stakeholder_ids_without_needs"] == ["st-1"]
    assert report["requirements_without_function_ids"] == ["req-1"]
    assert report["requirements_without_verification_ids"] == ["req-1"]
