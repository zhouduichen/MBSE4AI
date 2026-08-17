import pytest

from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    accept_initial_workbench,
    add_llm_suggestions,
    analyze_artifact,
    add_stakeholder,
    generate_draft_model,
    generate_model,
    empty_workbench,
    merge_artifact,
    remove_requirement,
    stakeholder_bundle,
)
from rflp_lite.application.scenarios import build_scenario
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.errors import ContractViolation


def test_reviewed_stakeholders_generate_stable_dynamic_rflp(monkeypatch):
    source = (
        "管理员必须恢复历史版本。\n"
        "审计人员必须查看恢复记录。\n"
        "普通用户应当只能查看自己的内容。"
    ).encode()

    state = analyze_artifact("requirements.txt", source)

    assert {item["name"] for item in state["stakeholders"]} >= {
        "管理员",
        "审计人员",
        "普通用户",
    }
    state = accept_traceable(state)
    state = generate_model(state)
    assert {item["layer"] for item in state["rflp"]["elements"]} == {
        "R",
        "F",
        "L",
        "P",
    }
    assert state["coverage"] == {"R-F": 100, "F-L": 100, "L-P": 100}
    assert state["svg"] == generate_model(state)["svg"]
    assert "管理员" in state["svg"]

    monkeypatch.delenv("RFLP_LLM_API_KEY", raising=False)
    with pytest.raises(AdapterFailure, match="LLM 未配置"):
        add_llm_suggestions(state)


def test_draft_model_is_available_before_review_without_mutating_candidates():
    state = analyze_artifact("requirements.txt", "管理员必须恢复历史版本。".encode())

    draft = generate_draft_model(state)

    assert draft["draft"] is True
    assert draft["rflp"] is None
    assert draft["draft_graph"]["items"]
    assert draft["svg"].startswith("<svg")
    assert "需求理解图" in draft["svg"]
    assert all(item["status"] == "candidate" for item in draft["claims"])
    assert state["rflp"] is None


def test_initial_workbench_accepts_rule_results_without_llm():
    state = analyze_artifact("requirements.txt", "系统应支持备份。".encode())

    accepted = accept_initial_workbench(state)

    assert accepted["claims"]
    assert all(item["status"] == "accepted" for item in accepted["claims"])
    assert all(item["status"] == "accepted" for item in accepted["structured_requirements"])
    assert accepted["review_queue"] == []


def test_initial_workbench_keeps_implicit_model_suggestion_reviewable():
    state = analyze_artifact("requirements.txt", "系统应支持备份。".encode())
    state["claims"].append(
        {
            "id": "implicit-1",
            "subject": "系统",
            "predicate": "应",
            "object": "应考虑恢复时间",
            "source_type": "inferred",
            "producer": "llm",
            "status": "candidate",
        }
    )

    accepted = accept_initial_workbench(state)

    assert next(item for item in accepted["claims"] if item["id"] == "implicit-1")["status"] == "candidate"
    assert any(item["item_id"] == "implicit-1" for item in accepted["review_queue"])


def test_draft_model_accepts_plain_language_as_provisional_nodes():
    state = analyze_artifact("requirements.txt", "希望系统支持历史版本恢复。".encode())

    draft = generate_draft_model(state)

    assert len(state["claims"]) == 1
    assert state["claims"][0]["source_type"] == "goal"
    assert state["claims"][0]["status"] == "candidate"
    assert draft["draft"] is True
    assert "未识别明确约束" in draft["draft_warnings"][0]
    assert any("历史版本恢复" in item["text"] for item in draft["draft_graph"]["items"])


def test_quality_attribute_phrase_becomes_a_traceable_requirement_candidate():
    state = analyze_artifact("requirements.txt", "要有高鲁棒性".encode())

    assert len(state["claims"]) == 1
    assert state["claims"][0]["subject"] == "待命名系统"
    assert state["claims"][0]["predicate"] == "应具备"
    assert state["claims"][0]["object"] == "高鲁棒性"
    assert state["claims"][0]["source_type"] == "constraint"

    accepted = accept_traceable(state)
    assert accepted["claims"][0]["status"] == "accepted"


def test_inferred_stakeholder_is_not_automatically_accepted():
    state = analyze_artifact("requirements.txt", "系统必须保留审计记录。".encode())
    state["stakeholders"].append(
        {
            "id": "stakeholder-inferred",
            "name": "审计人员",
            "candidate_type": "inferred",
            "source_span_id": state["spans"][0]["id"],
            "confidence": 0.7,
            "reason": "由审计要求推断",
            "producer": "llm",
            "status": "candidate",
        }
    )

    accepted = accept_traceable(state)

    assert accepted["stakeholders"][-1]["status"] == "candidate"


def test_merge_artifact_accumulates_candidates_and_dedups():
    first = analyze_artifact("a.txt", "管理员必须恢复历史版本。\n".encode())
    second_fresh = analyze_artifact("b.txt", "审计人员必须查看恢复记录。\n".encode())

    merged = merge_artifact(first, "b.txt", "审计人员必须查看恢复记录。\n".encode())
    assert {item["name"] for item in merged["stakeholders"]} >= {"管理员", "审计人员"}
    assert {item["id"] for item in merged["spans"]} == {item["id"] for item in first["spans"]} | {
        item["id"] for item in second_fresh["spans"]
    }
    assert merged["rflp"] is None
    assert merged["baseline"] is None

    again = merge_artifact(merged, "a.txt", "管理员必须恢复历史版本。\n".encode())
    assert len(again["spans"]) == len(merged["spans"])


def test_manual_stakeholder_bundle_collects_related_objects():
    state = analyze_artifact(
        "requirements.txt",
        "管理员必须恢复历史版本。\n".encode(),
    )
    state = add_stakeholder(state, "产品负责人")
    state = add_stakeholder(state, "管理员")
    bundle = stakeholder_bundle(state, "管理员")

    assert bundle["selected"]["name"] == "管理员"
    assert bundle["concerns"][0]["name"] == "故障恢复"
    assert bundle["needs"][0]["statement"] == "管理员必须恢复历史版本。"
    assert bundle["claims"][0]["subject"] == "管理员"
    assert any(item["name"] == "产品负责人" for item in state["stakeholders"])


def test_manual_stakeholder_can_start_an_empty_workbench():
    state = add_stakeholder(empty_workbench(), "运维人员")

    assert state["artifact"]["kind"] == "manual"
    assert state["stakeholders"][0]["name"] == "运维人员"
    assert stakeholder_bundle(state)["selected"]["name"] == "运维人员"


def test_stakeholder_categories_are_detected_and_can_be_overridden():
    state = analyze_artifact(
        "requirements.txt",
        "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。".encode(),
    )
    by_name = {item["name"]: item for item in state["stakeholders"]}

    assert by_name["管理员"]["category"] == "operator"
    assert by_name["审计人员"]["category"] == "regulator"

    state = add_stakeholder(state, "供应商", "engineering")
    supplier = next(item for item in state["stakeholders"] if item["name"] == "供应商")
    assert supplier["category"] == "engineering"
    assert supplier["category_label"] == "系统工程 / 研发"


def _deletion_fixture():
    state = analyze_artifact(
        "requirements.txt",
        "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。".encode(),
    )
    for claim in state["claims"]:
        claim["status"] = "accepted"
    claim_ids = [item["id"] for item in state["claims"]]
    structured_ids = [item["id"] for item in state["structured_requirements"]]
    automatic = []
    for claim_id in claim_ids:
        scenario = build_scenario(
            title=f"自动场景 {claim_id}",
            description="自动生成场景",
            steps=("执行",),
            expected_outcomes=("完成",),
            requirement_ids=(claim_id,),
        )
        scenario.update({"producer": "system", "generation_mode": "scenario-matrix"})
        automatic.append(scenario)
    manual = build_scenario(
        title="手动联合场景",
        description="人工维护场景",
        steps=("执行",),
        expected_outcomes=("完成",),
        requirement_ids=tuple(claim_ids),
    )
    state["scenarios"] = automatic + [manual]
    state["scenario_runs"] = [{"scenario_id": automatic[0]["id"], "run_id": "run-1"}]
    state["review_queue"] = [{"group": "claims", "item_id": claim_ids[0]}]
    state["change_set"] = {"items": [{"id": claim_ids[0]}]}
    state["rflp"] = {"elements": [{"id": "rflp-1"}], "relations": []}
    state["draft"] = False
    state["draft_graph"] = {"items": []}
    state["svg"] = "<svg></svg>"
    state["mbse"] = {"actors": [], "use_cases": []}
    state["baseline"] = {"id": "baseline-1"}
    return state, claim_ids, structured_ids


def test_remove_requirement_preserves_manual_data_and_clears_derived_results():
    state, claim_ids, structured_ids = _deletion_fixture()

    removed, metadata = remove_requirement(state, claim_ids[0])

    assert [item["id"] for item in removed["claims"]] == [claim_ids[1]]
    assert [item["id"] for item in removed["structured_requirements"]] == [structured_ids[1]]
    assert len(removed["scenarios"]) == 2
    manual = next(item for item in removed["scenarios"] if item["title"] == "手动联合场景")
    assert manual["requirement_ids"] == [claim_ids[1]]
    assert all(claim_ids[0] not in item.get("requirement_ids", ()) for item in removed["scenarios"])
    assert removed["scenario_runs"] == []
    assert removed["rflp"] is None
    assert removed["mbse"] is None
    assert removed["baseline"] is None
    assert metadata["requirement_id"] == claim_ids[0]


def test_remove_last_requirement_clears_current_input_but_keeps_artifact_metadata():
    state, claim_ids, _ = _deletion_fixture()
    state["claims"] = [state["claims"][0]]
    state["structured_requirements"] = [state["structured_requirements"][0]]
    manual = next(item for item in state["scenarios"] if item["title"] == "手动联合场景")
    manual["requirement_ids"] = [claim_ids[0]]

    removed, _ = remove_requirement(state, claim_ids[0])

    assert removed["claims"] == []
    assert removed["structured_requirements"] == []
    assert removed["spans"] == []
    assert removed["system_context"] is None
    assert removed["artifact"]
    assert len(removed["scenarios"]) == 1
    assert removed["scenarios"][0]["title"] == "手动联合场景"
    assert removed["scenarios"][0]["requirement_ids"] == []


def test_remove_requirement_rejects_unknown_id_without_mutating_state():
    state, _, _ = _deletion_fixture()

    with pytest.raises(ContractViolation, match="需求不存在"):
        remove_requirement(state, "requirement-missing")
