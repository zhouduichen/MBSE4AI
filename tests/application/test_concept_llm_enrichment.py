from __future__ import annotations

from typing import Any

from rflp_lite.application.concept_llm_enrichment import enrich_concept_input
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


class FixtureModel:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload
        self.calls = 0

    def complete_json(self, request: Any) -> GenerationResponse:
        self.calls += 1
        return GenerationResponse(
            request.lens_id,
            self.payload,
            canonical_hash(request.user_payload),
            canonical_hash(self.payload),
            False,
            provider_id="fixture",
            model_id="fixture-model",
        )


def _state() -> dict[str, object]:
    return {
        "project_scope": {"workspace": "concept", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "我想做一个适合城市巡检的智能飞行器。"}],
        "spans": [{"id": "span-1", "text": "我想做一个适合城市巡检的智能飞行器。"}],
        "claims": [],
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "structured_requirements": [],
        "scenarios": [],
        "discovery": {},
    }


def _payload() -> dict[str, object]:
    return {
        "system": {
            "name": "城市巡检智能飞行器",
            "domain": "uncrewed aerial vehicle",
            "mission": "城市巡检",
        },
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "requirements": [],
        "scenarios": [],
        "architecture": {
            "functions": [],
            "logical_components": [],
            "physical_components": [],
            "interfaces": [],
            "relations": [],
        },
        "open_questions": ["续航时间", "任务载荷"],
        "concept_proposal": {
            "summary": "城市巡检智能飞行器概念",
            "alternatives": ["固定翼长航时", "多旋翼低速悬停"],
            "rationale": ["输入强调城市巡检", "任务细节仍需补充"],
            "assumptions": ["暂未指定续航和载荷"],
            "parameter_suggestions": [
                {
                    "name": "cruise_speed_mps",
                    "value": 28,
                    "unit": "m/s",
                    "reason": "巡检初始估计",
                }
            ],
        },
    }


def test_enriches_broad_intent_with_llm_concept_and_typed_suggestions() -> None:
    model = FixtureModel(_payload())
    result = enrich_concept_input(
        _state(),
        active_config={"kind": "local", "model": "fixture"},
        model_factory=lambda _config: model,
    )

    assert model.calls == 1
    assert result.status == "completed"
    assert result.state["llm_analysis"]["system"]["domain"] == "uncrewed aerial vehicle"
    assert result.concept_proposal["summary"] == "城市巡检智能飞行器概念"
    suggestion = result.parameter_suggestions[0]
    assert suggestion["name"] == "cruise_speed_mps"
    assert suggestion["producer"] == "llm"
    assert suggestion["candidate_type"] == "suggested"
    assert suggestion["analysis_input_hash"] == "input-1"


def test_llm_unavailable_is_a_fallback_without_fabricated_fixed_wing_output() -> None:
    result = enrich_concept_input(
        _state(),
        active_config=None,
        model_factory=lambda _config: None,
    )

    assert result.status == "fallback"
    assert result.concept_proposal == {}
    assert result.parameter_suggestions == ()
    assert result.state["llm_analysis"] == {}
    assert result.diagnostics
    assert "fixed-wing" not in " ".join(result.diagnostics).lower()
