from __future__ import annotations

import pytest

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from tests.mbse_benchmark.runners.experiment_contract import (
    BenchmarkInputEnvelope,
    EvaluationSpec,
    assert_model_visible_payload,
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


def test_repeat_summary_reports_sample_dispersion_and_ci() -> None:
    summary = summarize_repeats([{"quality": 0.4}, {"quality": 0.6}, {"quality": 0.8}])

    assert summary["quality"]["count"] == 3
    assert summary["quality"]["mean"] == 0.6
    assert summary["quality"]["std"] > 0
    assert summary["quality"]["ci95"][0] < 0.6 < summary["quality"]["ci95"][1]
