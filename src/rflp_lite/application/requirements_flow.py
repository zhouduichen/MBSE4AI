from __future__ import annotations

from rflp_lite.application.project_bridge import approve_workbench_baseline
from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    generate_draft_model,
    generate_model,
)
from rflp_lite.application.scenario_execution import append_scenario_run, execute_scenario
from rflp_lite.application.scenarios import add_scenario
from rflp_lite.domain.canonical import canonical_hash, canonical_json


def _clone(value: dict[str, object]) -> dict[str, object]:
    import json

    return json.loads(canonical_json(value))


def _generated_scenario(result: dict[str, object], claim: dict[str, object]) -> dict[str, object]:
    subject = str(claim.get("subject") or "使用者").strip()
    objective = str(claim.get("object") or "完成需求").strip().rstrip("。.")
    return {
        "title": f"{subject}：{objective[:28]}",
        "description": f"根据需求“{objective}”生成的最小可执行场景，后续可在场景描述模块细化。",
        "actors": subject,
        "preconditions": (),
        "steps": (f"{subject}发起请求", f"系统处理：{objective}", "确认处理结果"),
        "expected_outcomes": (f"完成：{objective}",),
        "faults": (),
        "requirement_ids": (str(claim["id"]),),
    }


def _draft_system_scenario(result: dict[str, object]) -> dict[str, object]:
    context = result.get("system_context") or {}
    system_name = str(context.get("name") or "待命名系统")
    claim_ids = tuple(
        str(claim["id"])
        for claim in result.get("claims", ())
        if claim.get("source_type") == "provisional"
    )
    return {
        "title": f"{system_name}定义",
        "description": f"围绕“{system_name}”建立第一版系统边界和需求草案，后续可继续细化为正式场景。",
        "actors": ("需求提出者", "系统设计团队"),
        "preconditions": (),
        "steps": ("明确系统任务目标", "识别核心功能与外部接口", "记录约束、风险和验证方式"),
        "expected_outcomes": (f"形成可继续细化的{system_name}系统草案",),
        "faults": (),
        "requirement_ids": claim_ids,
    }


def run_requirements_flow(state: dict[str, object]) -> dict[str, object]:
    """Run the user-entered requirement through the local model workbench.

    This is an experience-mode orchestration of the real local adapters. It
    does not use the fixed demo fixture and marks its generated scenario and
    baseline so users can distinguish quick output from reviewed delivery.
    """
    result = accept_traceable(state)
    result["flow"] = None
    if not any(item.get("status") == "accepted" for item in result.get("claims", ())):
        result = generate_draft_model(result)
        draft_scenario_ids: list[str] = []
        if result.get("claims") and not result.get("scenarios"):
            result = add_scenario(result, **_draft_system_scenario(result))
            scenario = result["scenarios"][-1]
            scenario["status"] = "generated-draft"
            scenario["producer"] = "rule"
            scenario["generated_from"] = "system-context"
            execution = execute_scenario(result, scenario["id"])
            result = append_scenario_run(result, execution)
            draft_scenario_ids.append(scenario["id"])
        result["flow"] = {
            "status": "draft_only",
            "steps": [
                {"key": "analysis", "status": "completed"},
                {"key": "draft_graph", "status": "completed"},
                {"key": "starter_scenario", "status": "completed", "count": len(draft_scenario_ids)},
                {"key": "scenario_execution", "status": "completed", "count": len(draft_scenario_ids)},
                {"key": "formal_model", "status": "waiting_for_requirement_review"},
                {"key": "project_validation", "status": "waiting_for_project_path"},
            ],
            "warning": "原文已建立系统主题、初始 RFLP 草图和起始场景；补充目标、功能和约束后即可确认正式需求。",
            "next_action": "去需求输入补充系统目标、核心功能和接口约束",
        }
        return result

    result = generate_model(result)
    result, baseline = approve_workbench_baseline(result)
    result["baseline"]["approval_mode"] = "quick-flow"
    result["baseline"]["approval_note"] = "一键体验流程自动生成；正式交付前请人工复核。"

    existing_requirement_ids = {
        requirement_id
        for scenario in result.get("scenarios", ())
        for requirement_id in scenario.get("requirement_ids", ())
    }
    generated_ids: list[str] = []
    for claim in result["claims"]:
        if claim["status"] != "accepted" or claim["id"] in existing_requirement_ids:
            continue
        result = add_scenario(result, **_generated_scenario(result, claim))
        scenario = next(
            item
            for item in result["scenarios"]
            if claim["id"] in item.get("requirement_ids", ())
        )
        scenario["status"] = "generated"
        scenario["producer"] = "rule"
        scenario["generated_from"] = claim["id"]
        generated_ids.append(scenario["id"])

    completed_scenario_ids = {
        run["scenario_id"]
        for run in result.get("scenario_runs", ())
        if run.get("status") == "completed"
    }
    scenario_ids_to_execute = [
        scenario["id"]
        for scenario in result["scenarios"]
        if scenario["id"] not in completed_scenario_ids
    ]
    for scenario_id in scenario_ids_to_execute:
        execution = execute_scenario(result, scenario_id)
        result = append_scenario_run(result, execution)

    result["flow"] = {
        "status": "completed",
        "steps": [
            {"key": "analysis", "status": "completed"},
            {"key": "stakeholders", "status": "completed"},
            {"key": "formal_model", "status": "completed"},
            {"key": "baseline", "status": "completed"},
            {"key": "scenarios", "status": "completed", "count": len(result["scenarios"])},
            {"key": "scenario_execution", "status": "completed", "count": len(scenario_ids_to_execute)},
            {"key": "project_validation", "status": "waiting_for_project_path"},
        ],
        "baseline_hash": baseline.hash,
        "warning": "这是基于当前需求的快速体验闭环；场景执行为本地声明式轨迹，真实项目验证仍需提供项目目录。",
        "flow_hash": canonical_hash(
            (result.get("artifact"), result.get("rflp"), result.get("scenarios"), result.get("baseline"))
        ),
    }
    return _clone(result)
