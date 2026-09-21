from __future__ import annotations

import pytest

from rflp_lite.ports.generative_model import GenerationResponse
from tests.mbse_benchmark.runners.experiment_contract import EvaluationSpec
from tests.mbse_benchmark.runners.scenario_pipeline import (
    ModelGraphNormalizer,
    ScenarioRunner,
)
from tests.mbse_benchmark.scenarios import BenchmarkScenario, scenario_contract


CASE = {
    "case_id": "CASE-01",
    "system": "测试系统",
    "brief": "系统用于验证统一 benchmark 输入",
    "stakeholders": ["用户"],
    "lifecycle_stages": ["设计"],
    "scenarios": [{"id": "nominal", "name": "正常运行", "category": "normal", "text": "正常运行"}],
    "requirements": [{"id": "REQ-1", "statement": "系统应完成任务", "verification_method": "test"}],
}


def _payload() -> dict[str, object]:
    return {
        "project_id": "p1",
        "revision": 0,
        "entities": [
            {"id": "req-1", "kind": "requirement", "name": "系统应完成任务", "status": "candidate", "producer": "llm", "payload": {"statement": "系统应完成任务", "verification_method": "test"}},
            {"id": "fn-1", "kind": "function", "name": "完成任务", "status": "candidate", "producer": "llm", "payload": {}},
        ],
        "relations": [
            {"id": "rel-1", "source_id": "req-1", "predicate": "satisfiedBy", "target_id": "fn-1"},
        ],
    }


class RecordingModel:
    _config = {"provider_id": "test-provider", "model": "test-model", "temperature": 0.2}

    def __init__(self):
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        return GenerationResponse(
            request.lens_id,
            _payload(),
            "input-hash",
            "output-hash",
            False,
            provider_id="test-provider",
            model_id="test-model",
            duration_ms=3,
            usage={"total_tokens": 42},
        )


def test_one_shot_and_staged_scenarios_call_the_same_model_without_expected_graph():
    model = RecordingModel()
    runner = ScenarioRunner(ModelGraphNormalizer())

    one_shot = runner.run(CASE, scenario_contract(BenchmarkScenario.A_BARE_ONE_SHOT), model, project_id="p1")
    staged = runner.run(CASE, scenario_contract(BenchmarkScenario.B_BARE_STAGED), model, project_id="p1")

    assert len(model.requests) == 6
    assert len(model.requests[0].user_payload["case_input"]["scenarios"]) == 1
    assert all("requirements" in request.user_payload["case_input"] for request in model.requests)
    assert one_shot.metadata.input_hash == staged.metadata.input_hash
    assert one_shot.metadata.model == staged.metadata.model == "test-model"
    assert one_shot.metadata.provider == staged.metadata.provider == "test-provider"
    assert one_shot.metadata.verifier_enabled is False
    assert staged.metadata.repair_enabled is False
    assert one_shot.graph.snapshot_hash


def test_bare_runner_rejects_evaluator_only_aliases_before_model_call():
    model = RecordingModel()
    case = {**CASE, "expectedGraph": {"shortcut": True}}

    with pytest.raises(ValueError, match="evaluator-only"):
        ScenarioRunner().run(
            case,
            scenario_contract(BenchmarkScenario.A_BARE_ONE_SHOT),
            model,
            project_id="p1",
            evaluation_spec=EvaluationSpec.from_expectations({"shortcut": True}),
        )

    assert model.requests == []


def test_model_graph_normalizer_preserves_ids_and_remaps_relations():
    graph = ModelGraphNormalizer().normalize(_payload(), project_id="fallback")

    assert graph.project_id == "p1"
    assert {entity.id for entity in graph.entities} == {"req-1", "fn-1"}
    assert graph.relations[0].source_id == "req-1"
    assert graph.relations[0].target_id == "fn-1"


def test_model_graph_normalizer_removes_model_lifecycle_authority_claims():
    normalized = ModelGraphNormalizer().normalize_with_audit({
        "project_id": "p1",
        "entities": [{
            "id": "req-1",
            "kind": "requirement",
            "name": "系统需求",
            "status": "accepted",
            "producer": "user",
            "payload": {"statement": "系统应完成任务"},
        }],
        "relations": [],
    })

    entity = normalized.graph.entities[0]
    assert entity.meta.status.value == "candidate"
    assert entity.meta.producer.value == "llm"
    assert normalized.audit.authority_violations == ("req-1",)
    assert normalized.audit.claimed_statuses["req-1"] == "accepted"


def test_metadata_contains_reproducibility_fields():
    model = RecordingModel()
    result = ScenarioRunner().run(
        CASE,
        scenario_contract(BenchmarkScenario.A_BARE_ONE_SHOT),
        model,
        project_id="p1",
    )

    metadata = result.metadata.as_dict()
    required = {
        "scenario", "model", "provider", "prompt_hash", "task_spec_hash",
        "temperature", "input_hash", "token_usage", "latency_ms", "graph_hash",
        "verifier_enabled", "repair_enabled", "cas_enabled",
    }
    assert required <= metadata.keys()
    assert metadata["token_usage"] == {"total_tokens": 42}
    assert metadata["temperature"] == 0.2
