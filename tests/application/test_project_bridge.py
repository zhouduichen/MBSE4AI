from pathlib import Path

import pytest

from rflp_lite.application.project_bridge import (
    analyze_project_state,
    approve_workbench_baseline,
    execute_tests_state,
    verify_contracts_state,
)
from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    analyze_artifact,
    generate_model,
    review_item,
)
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "versioned-content-service"

REQUIREMENTS = (
    "管理员必须恢复历史版本。\n"
    "The service shall restore a historical version.\n"
    "The service must record an audit event for every restore.\n"
    "审计人员必须查看恢复记录。"
)


def _prepared_state() -> dict[str, object]:
    state = analyze_artifact("requirements.txt", REQUIREMENTS.encode())
    state = accept_traceable(state)
    return generate_model(state)


def test_approve_requires_generated_rflp():
    state = analyze_artifact("requirements.txt", "管理员必须恢复历史版本。".encode())
    with pytest.raises(ContractViolation, match="请先生成 RFLP 规划图"):
        approve_workbench_baseline(state)


def test_approve_sets_baseline_and_clears_project():
    state = _prepared_state()
    state, baseline = approve_workbench_baseline(state)
    assert state["baseline"]["id"] == baseline.id
    assert state["baseline"]["hash"] == baseline.hash
    assert state["baseline"]["status"] == "approved"
    assert all(item["status"] == "approved" for item in state["baseline"]["elements"])
    assert state["project"] is None


def test_analyze_requires_approved_baseline():
    state = _prepared_state()
    with pytest.raises(ContractViolation, match="请先批准基线"):
        analyze_project_state(state, str(EXAMPLE))


def test_full_chain_produces_matches_delta_tasks_evidence():
    state = _prepared_state()
    state, _ = approve_workbench_baseline(state)
    state, artifacts = analyze_project_state(state, str(EXAMPLE))

    project = state["project"]
    assert project["baseline_hash"] == artifacts.baseline.hash
    assert artifacts.delta.baseline_hash == artifacts.baseline.hash
    assert artifacts.actual.id.startswith("actualmodel-")
    assert project["tasks"], "task contracts should be derived from a non-empty delta"
    assert project["evidence"]
    assert project["summary"]["matched"] >= 1
    assert project["summary"]["files_used"] >= 1

    kinds = {item["kind"] for item in project["delta"]["items"]}
    assert kinds <= {"MISSING", "EXTRA"}
    assert kinds == {"MISSING", "EXTRA"}

    actual_ids = {element["id"] for element in project["actual"]["elements"]}
    for evidence in project["evidence"]:
        assert evidence["kind"] in {
            "python-module",
            "python-class",
            "python-function",
            "openapi-operation",
            "test-case",
        }
        assert evidence["target_id"] in actual_ids


def test_full_chain_is_deterministic():
    def run():
        state = _prepared_state()
        state, _ = approve_workbench_baseline(state)
        state, artifacts = analyze_project_state(state, str(EXAMPLE))
        return canonical_json(state["project"]), artifacts

    first_json, first = run()
    second_json, second = run()
    assert first_json == second_json
    assert first.delta.id == second.delta.id
    assert first.actual.id == second.actual.id
    assert first.evidence == second.evidence


def test_review_invalidates_baseline_and_project():
    state = _prepared_state()
    state, _ = approve_workbench_baseline(state)
    state, _ = analyze_project_state(state, str(EXAMPLE))
    assert state["project"] is not None

    stakeholder = state["stakeholders"][0]
    state = review_item(state, "stakeholders", stakeholder["id"], "rejected")

    assert state["baseline"] is None
    assert state["project"] is None
    assert state["rflp"] is None


def test_generate_model_invalidates_baseline_and_project():
    state = _prepared_state()
    state, _ = approve_workbench_baseline(state)
    state, _ = analyze_project_state(state, str(EXAMPLE))
    assert state["project"] is not None

    state = generate_model(state)

    assert state["baseline"] is None
    assert state["project"] is None
    assert state["coverage"]


def _single_obligation_rflp(state: dict[str, object]) -> dict[str, object]:
    state = accept_traceable(state)
    state = generate_model(state)
    state, _ = approve_workbench_baseline(state)
    return state


def test_verify_requires_baseline():
    state = _prepared_state()
    with pytest.raises(ContractViolation, match="请先批准基线"):
        verify_contracts_state(state, str(EXAMPLE))


def test_verify_requires_existing_tasks():
    state = _prepared_state()
    state, _ = approve_workbench_baseline(state)
    with pytest.raises(ContractViolation, match="请先在项目接入中分析项目并生成任务契约"):
        verify_contracts_state(state, str(EXAMPLE))


def test_verify_reports_contracts_resolved_after_implementation(tmp_path: Path):
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state = _single_obligation_rflp(state)

    project = tmp_path / "proj"
    project.mkdir()
    (project / "proj.py").write_text("# placeholder\n", encoding="utf-8")
    state, _ = analyze_project_state(state, str(project))
    tasks = state["project"]["tasks"]
    assert len(tasks) == 2
    assert {task["target_ids"][0].split("-", 1)[0] for task in tasks} == {"req", "fn"}

    (project / "proj.py").write_text(
        "def restore_historical_version():\n    pass\n", encoding="utf-8"
    )
    state, verify = verify_contracts_state(state, str(project))

    assert len(verify.statuses) == 2
    assert all(item["status"] == "RESOLVED" for item in verify.statuses)
    summary = state["project"]["execution"]["summary"]
    assert summary["resolved"] == 2
    assert summary["unresolved"] == 0
    assert summary["missing"] == 0
    assert summary["extra"] == 0


def test_verify_is_deterministic(tmp_path: Path):
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state = _single_obligation_rflp(state)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "proj.py").write_text("# placeholder\n", encoding="utf-8")
    state, _ = analyze_project_state(state, str(project))

    state, first = verify_contracts_state(state, str(project))
    first_json = canonical_json(state["project"]["execution"])
    state, second = verify_contracts_state(state, str(project))
    second_json = canonical_json(state["project"]["execution"])
    assert first.hash == second.hash
    assert first.statuses == second.statuses
    assert first_json == second_json


def test_verify_is_invalidated_by_model_change(tmp_path: Path):
    state = _prepared_state()
    state, _ = approve_workbench_baseline(state)
    state, _ = analyze_project_state(state, str(EXAMPLE))
    state, _ = verify_contracts_state(state, str(EXAMPLE))
    assert state["project"]["execution"] is not None

    state = generate_model(state)

    assert state["project"] is None


def test_execute_tests_requires_baseline():
    state = _prepared_state()
    with pytest.raises(ContractViolation, match="请先批准基线"):
        execute_tests_state(state, str(EXAMPLE))


def test_execute_tests_requires_existing_tasks():
    state = _prepared_state()
    state, _ = approve_workbench_baseline(state)
    with pytest.raises(ContractViolation, match="请先在项目接入中分析项目并生成任务契约"):
        execute_tests_state(state, str(EXAMPLE))


def test_execute_tests_runs_and_records_test_run(tmp_path: Path):
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state = _single_obligation_rflp(state)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    state, _ = analyze_project_state(state, str(project))

    state, verify = execute_tests_state(state, str(project), timeout=120)

    test_run = state["project"]["execution"]["summary"]["test_run"]
    assert test_run["returncode"] == 0
    assert test_run["timed_out"] is False
    assert test_run["tests_passed"] == 1
    assert test_run["tests_failed"] == 0
    assert test_run["junit_evidence"] == 1
    assert test_run["stderr_tail"] == ""
    assert any(item.kind == "test-case" for item in verify.evidence)


def test_execute_tests_is_deterministic(tmp_path: Path):
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state = _single_obligation_rflp(state)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    state, _ = analyze_project_state(state, str(project))

    state, _ = execute_tests_state(state, str(project), timeout=120)
    first = canonical_json(state["project"]["execution"])
    state, _ = execute_tests_state(state, str(project), timeout=120)
    second = canonical_json(state["project"]["execution"])

    assert first == second


def test_execute_tests_populates_evidence_and_failed_tests(tmp_path: Path):
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state = _single_obligation_rflp(state)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    (project / "test_bad.py").write_text(
        "def test_broken():\n    assert False\n", encoding="utf-8"
    )
    state, _ = analyze_project_state(state, str(project))

    state, _ = execute_tests_state(state, str(project), timeout=120)

    test_run = state["project"]["execution"]["summary"]["test_run"]
    assert test_run["tests_passed"] == 1
    assert test_run["tests_failed"] == 1
    assert test_run["failed_tests"] == ["test_broken"]
    assert any(item["kind"] == "test-case" for item in state["project"]["evidence"])


def test_execute_tests_records_stderr_tail_on_failure(tmp_path: Path):
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state = _single_obligation_rflp(state)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_broken.py").write_text(
        "import nonexistent_module_xyz\n", encoding="utf-8"
    )
    state, _ = analyze_project_state(state, str(project))

    state, _ = execute_tests_state(state, str(project), timeout=120)

    test_run = state["project"]["execution"]["summary"]["test_run"]
    assert test_run["returncode"] != 0
    assert test_run["stderr_tail"] != ""