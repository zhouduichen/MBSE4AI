from __future__ import annotations

import json

import pytest

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.model import ModelGraph
from rflp_lite.ports.generative_model import (
    GenerationCallEvent,
    GenerationRequest,
    GenerationResponse,
)
from tests.mbse_benchmark.runners.case_runner import (
    _EvaluatorBoundaryModel,
    _apply_scenario_runtime_controls,
    _failure_metadata,
    _harness_metadata,
    _run_analysis,
)
from tests.mbse_benchmark.runners import case_runner as case_runner_module
from tests.mbse_benchmark.runners.experiment_contract import (
    BenchmarkInputEnvelope,
    EvaluationSpec,
    input_artifact_sha256,
    model_visible_key_tokens,
)
from tests.mbse_benchmark.runners.scenario_pipeline import (
    EXTERNAL_EVALUATOR_ID,
    TASK_SPEC,
)
from tests.mbse_benchmark.scenarios import BenchmarkScenario, scenario_contract


class _GenerationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def generate(self, project_id: str, *, document_ids: tuple[str, ...], force_new: bool) -> str:
        assert force_new is True
        self.calls.append((project_id, document_ids))
        return "vertical-result"


class _AnalysisService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, project_id: str, *, force_new: bool) -> str:
        assert force_new is True
        self.calls.append(project_id)
        return "lifecycle-result"


class _Services:
    def __init__(self) -> None:
        self.generation_service = _GenerationService()
        self.analysis_service = _AnalysisService()

    def generation(self, project_id: str) -> _GenerationService:
        return self.generation_service

    def analysis(self, project_id: str) -> _AnalysisService:
        return self.analysis_service


def test_vertical_benchmark_path_calls_product_generation_service() -> None:
    services = _Services()

    result = _run_analysis(
        services,
        "case-04",
        {"document_id": "document-case-04", "region_count": 3},
        {"provider": "remote"},
        "vertical",
    )

    assert result == "vertical-result"
    assert services.generation_service.calls == [("case-04", ("document-case-04",))]
    assert services.analysis_service.calls == []


def test_vertical_benchmark_path_does_not_treat_fixture_id_as_readable_document() -> None:
    services = _Services()

    result = _run_analysis(
        services,
        "case-04",
        {"document_id": "fixture-case-04", "region_count": 0},
        {"provider": "remote"},
        "vertical",
    )

    assert result == "vertical-result"
    assert services.generation_service.calls == [("case-04", ())]


def test_lifecycle_benchmark_path_keeps_legacy_workflow_entrypoint() -> None:
    services = _Services()

    result = _run_analysis(services, "case-04", {}, None, "lifecycle")

    assert result == "lifecycle-result"
    assert services.analysis_service.calls == ["case-04"]
    assert services.generation_service.calls == []


def test_harness_metadata_uses_the_same_profile_identity_as_bare_adapter() -> None:
    metadata = _harness_metadata(
        BenchmarkInputEnvelope.from_case({
            "case_id": "CASE-01",
            "system": "测试系统",
            "stakeholders": [],
            "lifecycle_stages": [],
            "scenarios": [],
            "requirements": [],
        }),
        scenario_contract(BenchmarkScenario.E_FULL_HARNESS),
        ModelGraph("case-01", (), (), 0),
        {"id": "profile-a", "provider": "openai-compatible", "model": "model-a"},
        {},
        telemetry_events=[],
        comparison_mode="natural",
        total_output_token_budget=None,
        execution_elapsed=0.001,
    )

    assert metadata["provider"] == "profile-a"
    assert metadata["task_spec_hash"] == canonical_hash(TASK_SPEC)
    assert metadata["runtime_task_spec_hash"] == ""
    assert metadata["input_artifact_byte_length"] == len(
        BenchmarkInputEnvelope.from_case({
            "case_id": "CASE-01",
            "system": "测试系统",
            "stakeholders": [],
            "lifecycle_stages": [],
            "scenarios": [],
            "requirements": [],
        }).canonical_bytes
    ) + 1


def test_failure_metadata_preserves_input_and_transport_telemetry() -> None:
    envelope = BenchmarkInputEnvelope.from_case({
        "case_id": "CASE-01",
        "system": "测试系统",
        "stakeholders": [],
        "lifecycle_stages": [],
        "scenarios": [],
        "requirements": [],
    })
    metadata = _failure_metadata(
        envelope,
        scenario_contract(BenchmarkScenario.A_BARE_ONE_SHOT),
        {
            "id": "profile-a",
            "provider": "openai-compatible",
            "model": "model-a",
            "benchmark_token_budget": 8192,
            "temperature": 0.0,
        },
        telemetry_events=[GenerationCallEvent(
            "bare",
            "initial",
            "profile-a",
            "model-a",
            1234,
            "completed",
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )],
        comparison_mode="natural",
        total_output_token_budget=None,
        execution_elapsed=1.5,
        evaluation_spec_hash="evaluation-hash",
        evaluator_id=EXTERNAL_EVALUATOR_ID,
        request_guard_hash="guard-hash",
    )

    assert metadata["failure_metadata"] is True
    assert metadata["input_hash"] == envelope.input_hash
    assert metadata["input_artifact_sha256"] == input_artifact_sha256(envelope)
    assert metadata["graph_hash"] is None
    assert metadata["telemetry"]["call_count"] == 1
    assert metadata["telemetry"]["total_tokens"] == 30
    assert metadata["telemetry"]["provider_latency_ms"] == 1234
    assert metadata["telemetry"]["wall_latency_ms"] == 1500
    assert metadata["evaluation_owner"] == EXTERNAL_EVALUATOR_ID
    assert metadata["evaluation_spec_hash"] == "evaluation-hash"
    assert metadata["ground_truth_model_visible"] is False
    assert metadata["evaluation_boundary"] == {
        "owner": EXTERNAL_EVALUATOR_ID,
        "model_visible": False,
        "ground_truth_payload_transmitted": False,
        "guard_enforced": True,
        "request_guard": "value_free_evaluator_key_tokens",
        "request_guard_hash": "guard-hash",
        "evaluation_spec_hash": "evaluation-hash",
    }


def test_run_case_persists_input_before_worker_start(tmp_path, monkeypatch) -> None:
    class FakeProcess:
        exitcode = 0

        def start(self):
            return None

        def join(self, _timeout):
            return None

        def is_alive(self):
            return False

    class FakeContext:
        def Process(self, **_kwargs):
            return FakeProcess()

    monkeypatch.setattr(
        case_runner_module.multiprocessing,
        "get_context",
        lambda _name: FakeContext(),
    )
    case = {
        "case_id": "CASE-01",
        "system": "测试系统",
        "stakeholders": [],
        "lifecycle_stages": [],
        "scenarios": [],
        "requirements": [],
    }

    case_runner_module.run_case(case, tmp_path, repeat_index=1)

    assert (tmp_path / "repeat_01" / "input.json").read_bytes()
    metadata = json.loads((tmp_path / "repeat_01" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["ground_truth_model_visible"] is False
    assert metadata["evaluation_boundary"]["guard_enforced"] is True


def test_harness_model_guard_blocks_evaluator_payload_before_provider_call() -> None:
    calls: list[GenerationRequest] = []

    class RecordingModel:
        def complete_json(self, request: GenerationRequest) -> GenerationResponse:
            calls.append(request)
            return GenerationResponse(
                request.lens_id,
                {"items": []},
                "input",
                "output",
                False,
            )

    evaluator = EvaluationSpec.from_expectations({"known_conflicts": {"CASE-01": []}})
    guarded = _EvaluatorBoundaryModel(
        RecordingModel(),
        model_visible_key_tokens(evaluator),
    )

    with pytest.raises(ValueError, match="evaluator-only"):
        guarded.complete_json(GenerationRequest(
            "benchmark.harness",
            "return JSON",
            {"context": {"known_conflicts": {"CASE-01": []}}},
            {"type": "object"},
        ))

    assert calls == []


def test_scenario_runtime_controls_make_repair_ablation_operational() -> None:
    base = {
        "vertical_feedback": False,
        "automatic_operational_completion": False,
        "vertical_completion_bridge": False,
    }

    repair_enabled = _apply_scenario_runtime_controls(
        base,
        scenario_contract(BenchmarkScenario.E_FULL_HARNESS),
    )
    repair_disabled = _apply_scenario_runtime_controls(
        base,
        scenario_contract(BenchmarkScenario.D_HARNESS_NO_REPAIR),
    )

    assert repair_enabled["vertical_feedback"] is True
    assert repair_enabled["automatic_operational_completion"] is True
    assert repair_enabled["vertical_completion_bridge"] is True
    assert repair_disabled["vertical_feedback"] is False
    assert repair_disabled["automatic_operational_completion"] is False
    assert repair_disabled["vertical_completion_bridge"] is False
