from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from typing import Any

from rflp_lite.application.intelligent_concept_workflow import (
    ConceptWorkflowOrchestrator,
    ConceptWorkflowRequest,
)
from rflp_lite.bootstrap.container import build_container
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


TEXT = (
    "设计一型中程侦察无人机，最大起飞重量不超过 650 kg，任务载荷至少 150 kg，"
    "翼展 ≤ 16 m，巡航速度 >= 240 km/h，机翼面积等于 24 m2，机身长度等于 9 m，"
    "截面模量等于 0.032 m3，许用应力等于 205000000 Pa，重心位置等于 2.7 m。"
)


class FixtureModel:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def complete_json(self, request: Any) -> GenerationResponse:
        return GenerationResponse(
            request.lens_id,
            self.payload,
            canonical_hash(request.user_payload),
            canonical_hash(self.payload),
            False,
            provider_id="fixture",
            model_id="concept-fixture",
        )


def _llm_payload() -> dict[str, object]:
    return {
        "system": {"name": "城市巡检固定翼", "domain": "uncrewed aerial vehicle", "mission": "城市巡检"},
        "stakeholders": [], "concerns": [], "needs": [], "requirements": [],
        "scenarios": [],
        "architecture": {"functions": [], "logical_components": [], "physical_components": [], "interfaces": [], "relations": []},
        "open_questions": ["续航时间"],
        "concept_proposal": {
            "summary": "城市巡检固定翼概念",
            "alternatives": ["固定翼长航时", "多旋翼悬停"],
            "rationale": ["适合大范围巡检"],
            "assumptions": ["初步按固定翼估计"],
            "parameter_suggestions": [
                {"name": "mass_kg", "value": 650, "unit": "kg"},
                {"name": "payload_kg", "value": 150, "unit": "kg"},
                {"name": "wing_area_m2", "value": 24, "unit": "m2"},
                {"name": "span_m", "value": 16, "unit": "m"},
                {"name": "fuselage_length_m", "value": 9, "unit": "m"},
                {"name": "cruise_speed_mps", "value": 66.67, "unit": "m/s"},
                {"name": "section_modulus_m3", "value": 0.032, "unit": "m3"},
                {"name": "allowable_stress_pa", "value": 205000000, "unit": "Pa"},
                {"name": "cg_x_m", "value": 2.7, "unit": "m"},
            ],
        },
    }


def test_workflow_runs_seven_steps_and_is_idempotent(tmp_path: Path) -> None:
    container = build_container(tmp_path / "workspaces")
    facade = WebFacade(tmp_path / "workspaces", dependencies=container.dependencies)
    facade.create_workspace("concept")
    orchestrator = ConceptWorkflowOrchestrator(
        tmp_path / "workspaces", dependencies=container.dependencies
    )
    request = ConceptWorkflowRequest(workspace_name="concept", text=TEXT)

    first = orchestrator.run(request)
    second = orchestrator.run(request)

    assert first.status == "completed"
    assert first.run_id == second.run_id
    assert first.result_hash == second.result_hash
    assert [step["status"] for step in first.steps] == ["completed"] * 7
    assert first.envelope["parameters"]["cruise_speed_mps"] == 240 / 3.6
    assert first.optimization["iteration_records"]
    assert len(first.candidates) >= 7
    assert first.recommendation["candidate_id"] in first.optimization["front_candidate_ids"]

    restored = orchestrator.resume(first.run_id, "concept")
    assert restored.result_hash == first.result_hash


def test_workflow_selects_provisional_baseline_without_formal_approval(tmp_path: Path) -> None:
    container = build_container(tmp_path / "workspaces")
    facade = WebFacade(tmp_path / "workspaces", dependencies=container.dependencies)
    facade.create_workspace("concept")
    orchestrator = ConceptWorkflowOrchestrator(
        tmp_path / "workspaces", dependencies=container.dependencies
    )
    result = orchestrator.run(ConceptWorkflowRequest(workspace_name="concept", text=TEXT))
    candidate_id = result.recommendation["candidate_id"]

    selected = orchestrator.select_as_concept_baseline(
        "concept", result.run_id, candidate_id, selected_by="tester", rationale="最优前沿候选"
    )

    assert selected["decision"] == "provisional_selected"
    assert selected["candidate_id"] == candidate_id
    assert selected["formal_status"] == result.formal_status
    assert selected["formal_status"] != "approved"


def test_empty_input_persists_failure_at_requirements_step(tmp_path: Path) -> None:
    container = build_container(tmp_path / "workspaces")
    facade = WebFacade(tmp_path / "workspaces", dependencies=container.dependencies)
    facade.create_workspace("concept")
    result = ConceptWorkflowOrchestrator(
        tmp_path / "workspaces", dependencies=container.dependencies
    ).run(ConceptWorkflowRequest(workspace_name="concept"))

    assert result.status == "failed"
    assert result.steps[0]["status"] == "failed"
    assert "empty" in " ".join(result.diagnostics).lower()


def test_broad_input_uses_llm_core_and_runs_without_history(tmp_path: Path) -> None:
    container = build_container(tmp_path / "workspaces")
    model = FixtureModel(_llm_payload())
    dependencies = replace(container.dependencies, model_factory=lambda _config: model)
    facade = WebFacade(tmp_path / "workspaces", dependencies=dependencies)
    facade.create_workspace("concept")
    orchestrator = ConceptWorkflowOrchestrator(
        tmp_path / "workspaces",
        dependencies=dependencies,
        llm_config_provider=lambda: {"kind": "local", "model": "fixture"},
    )

    result = orchestrator.run(
        ConceptWorkflowRequest(
            workspace_name="concept",
            text="我想做一个适合城市巡检的智能飞行器。",
            pack="auto",
            demo_mode=False,
        )
    )

    assert result.status == "completed"
    assert result.concept_proposal["summary"] == "城市巡检固定翼概念"
    assert result.llm_analysis["system"]["domain"] == "uncrewed aerial vehicle"
    assert result.domain_pack["id"] == "fixed-wing"
    assert result.candidates
    assert any(
        bool(step.get("artifacts", {}).get("temporary_baseline"))
        for step in result.steps
        if isinstance(step.get("artifacts"), dict)
    )


def test_generic_input_still_returns_a_concept_without_a_domain_pack(tmp_path: Path) -> None:
    container = build_container(tmp_path / "workspaces")
    facade = WebFacade(tmp_path / "workspaces", dependencies=container.dependencies)
    facade.create_workspace("concept")

    result = ConceptWorkflowOrchestrator(
        tmp_path / "workspaces", dependencies=container.dependencies
    ).run(ConceptWorkflowRequest(workspace_name="concept", text="我想做一个更安全的设备。"))

    assert result.status == "provisional"
    assert result.domain_pack == {}
    assert result.mbse
    assert result.status != "failed"
