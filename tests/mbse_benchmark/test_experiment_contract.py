from __future__ import annotations

import pytest

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from tests.mbse_benchmark.runners.experiment_contract import (
    BenchmarkInputEnvelope,
    EvaluationSpec,
    ExperimentTelemetry,
    GenerationCallEvent,
    assert_model_visible_payload,
    numeric_projection,
    summarize_repeats,
)


CASE = {
    "case_id": "CASE-01",
    "system": "测试系统",
    "brief": "完整 declared input",
    "stakeholders": ["用户"],
    "lifecycle_stages": ["设计"],
    "scenarios": [],
    "requirements": [{"id": "REQ-1", "statement": "系统应完成任务"}],
}


def test_case_envelope_uses_complete_declared_input() -> None:
    envelope = BenchmarkInputEnvelope.from_case(CASE)

    assert envelope.canonical_bytes == canonical_json(CASE).encode("utf-8")
    assert envelope.input_hash == canonical_hash(CASE)
    assert envelope.payload["requirements"] == CASE["requirements"]


def test_evaluator_spec_is_rejected_from_model_payload() -> None:
    spec = EvaluationSpec.from_expectations({"coverage": {"CASE-01": {}}})

    with pytest.raises(ValueError, match="evaluator-only"):
        assert_model_visible_payload({"evaluation_spec": spec.payload}, spec)

    with pytest.raises(ValueError, match="evaluator-only"):
        assert_model_visible_payload({"known_conflicts": spec.payload}, spec)

    with pytest.raises(ValueError, match="evaluator-only"):
        assert_model_visible_payload({"expectedGraph": spec.payload}, spec)


def test_repeat_summary_reports_sample_dispersion_and_ci() -> None:
    summary = summarize_repeats([{"quality": 0.4}, {"quality": 0.6}, {"quality": 0.8}])

    assert summary["quality"]["count"] == 3
    assert summary["quality"]["mean"] == 0.6
    assert summary["quality"]["std"] > 0
    assert summary["quality"]["ci95"][0] < 0.6 < summary["quality"]["ci95"][1]


def test_telemetry_aggregates_calls_tokens_latency_and_cost() -> None:
    telemetry = ExperimentTelemetry.from_events(
        [
            GenerationCallEvent(
                "one-shot", "initial", "provider", "model", 8, "completed",
                {"input_tokens": 10, "output_tokens": 20},
            ),
            GenerationCallEvent(
                "one-shot", "structural_repair", "provider", "model", 4, "completed",
                {"input_tokens": 3, "output_tokens": 7},
            ),
        ],
        wall_latency_ms=20,
        comparison_mode="budget_matched",
        total_output_token_budget=27,
        input_cost_per_1m_tokens=1.0,
        output_cost_per_1m_tokens=2.0,
    )

    assert telemetry.call_count == 2
    assert telemetry.repair_call_count == 1
    assert telemetry.total_tokens == 40
    assert telemetry.token_usage_status == "available"
    assert telemetry.provider_latency_ms == 12
    assert telemetry.estimated_cost_usd == 0.000067
    assert telemetry.budget_exhausted is True


def test_telemetry_accepts_native_prompt_and_eval_counts() -> None:
    telemetry = ExperimentTelemetry.from_events([
        GenerationCallEvent(
            "native", "initial", "ollama", "model", 3, "completed",
            {"prompt_eval_count": 11, "eval_count": 7},
        ),
    ])

    assert telemetry.input_tokens == 11
    assert telemetry.output_tokens == 7
    assert telemetry.total_tokens == 18
    assert telemetry.token_usage_status == "available"


def test_telemetry_fails_closed_when_any_provider_call_lacks_complete_usage() -> None:
    telemetry = ExperimentTelemetry.from_events(
        [
            GenerationCallEvent(
                "first", "initial", "provider", "model", 3, "completed",
                {"input_tokens": 11, "output_tokens": 7},
            ),
            GenerationCallEvent(
                "second", "initial", "provider", "model", 3, "completed",
                {"input_tokens": 5},
            ),
        ],
        input_cost_per_1m_tokens=1.0,
        output_cost_per_1m_tokens=1.0,
    )

    assert telemetry.token_usage_status == "unavailable"
    assert telemetry.cost_status == "unavailable"
    assert telemetry.estimated_cost_usd is None


def test_numeric_projection_keeps_nested_semantic_governance_and_telemetry_metrics() -> None:
    projected = numeric_projection({
        "semantic": {"trace_accuracy": 0.75},
        "governance": {"release_closure": {"issue_count": 2}},
        "available": True,
    })

    assert projected == {
        "semantic.trace_accuracy": 0.75,
        "governance.release_closure.issue_count": 2.0,
    }
