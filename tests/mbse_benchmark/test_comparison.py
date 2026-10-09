from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.mbse_benchmark.runners.benchmark_runner import (
    _comparison_runtime_config,
    _persisted_input_audit,
    run_benchmark,
    run_scenario_comparison,
)
from tests.mbse_benchmark.runners import benchmark_runner as benchmark_runner_module
from tests.mbse_benchmark.runners.case_runner import _write_canonical_input
from tests.mbse_benchmark.runners.experiment_contract import (
    BenchmarkInputEnvelope,
    input_artifact_sha256,
)
from tests.mbse_benchmark.runners.scenario_pipeline import (
    EXTERNAL_EVALUATOR_ID,
    MODEL_GRAPH_NORMALIZER_ID,
)
from tests.mbse_benchmark.scenarios import (
    BenchmarkScenario,
    scenario_contract,
    validate_ablation_contracts,
)


CASE = {
    "case_id": "CASE-01",
    "system": "测试系统",
    "brief": "fair comparison",
    "stakeholders": [],
    "lifecycle_stages": [],
    "scenarios": [],
    "requirements": [{"id": "REQ-1", "statement": "系统应完成任务"}],
}


def test_c_d_e_change_only_the_declared_control() -> None:
    validate_ablation_contracts()
    c = scenario_contract(BenchmarkScenario.C_HARNESS_NO_VERIFIER)
    d = scenario_contract(BenchmarkScenario.D_HARNESS_NO_REPAIR)
    e = scenario_contract(BenchmarkScenario.E_FULL_HARNESS)

    assert (c.verifier_enabled, c.gate_enabled, c.repair_enabled, c.cas_enabled) == (False, True, True, True)
    assert (d.verifier_enabled, d.gate_enabled, d.repair_enabled, d.cas_enabled) == (True, True, False, True)
    assert (e.verifier_enabled, e.gate_enabled, e.repair_enabled, e.cas_enabled) == (True, True, True, True)


def test_bare_and_harness_input_files_use_identical_canonical_bytes(tmp_path: Path) -> None:
    envelope = BenchmarkInputEnvelope.from_case(CASE)
    path = tmp_path / "input.json"

    _write_canonical_input(path, envelope)

    assert path.read_bytes() == envelope.canonical_bytes + b"\n"


def test_persisted_input_audit_checks_every_scenario_and_repeat(tmp_path: Path) -> None:
    cases = (CASE,)
    for scenario in BenchmarkScenario:
        for repeat_index in range(1, 4):
            path = (
                tmp_path
                / scenario.value
                / "case_01"
                / f"repeat_{repeat_index:02d}"
                / "input.json"
            )
            _write_canonical_input(path, BenchmarkInputEnvelope.from_case(CASE))

    audit = _persisted_input_audit(tmp_path, cases, repeats=3)

    assert audit["checked_count"] == 15
    assert audit["all_present"] is True
    assert audit["all_exact"] is True
    assert all(
        item["observed_artifact_sha256"]
        == input_artifact_sha256(BenchmarkInputEnvelope.from_case(CASE))
        for item in audit["records"]
    )

    altered = (
        tmp_path
        / BenchmarkScenario.A_BARE_ONE_SHOT.value
        / "case_01"
        / "repeat_01"
        / "input.json"
    )
    altered.write_text("{}\n", encoding="utf-8")
    assert _persisted_input_audit(tmp_path, cases, repeats=3)["all_exact"] is False


def test_a_to_e_comparison_requires_three_repeats() -> None:
    with pytest.raises(ValueError, match="at least three repeats"):
        run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            Path("/tmp/ai4mbse-comparison-test"),
            repeats=2,
            report_dir=Path("/tmp/ai4mbse-comparison-report"),
            profile="test",
            runtime_config={"model": "test", "provider": "test"},
        )


def test_comparison_rejects_reused_output_root_before_model_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "old-report.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        benchmark_runner_module,
        "run_benchmark",
        lambda *args, **kwargs: pytest.fail("model execution started before stale-root guard"),
    )

    with pytest.raises(ValueError, match="output root must be empty"):
        run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            output_root,
            repeats=3,
            report_dir=tmp_path / "report",
            profile="test-profile",
            runtime_config={"model": "test-model", "provider": "test"},
        )


def test_comparison_rejects_a_vertical_budget_below_runtime_floor() -> None:
    with pytest.raises(ValueError, match="at least 256 tokens"):
        _comparison_runtime_config({"benchmark_token_budget": 128})


def _fake_comparison_record(scenario: str, repeat_index: int, mode: str) -> dict[str, object]:
    contract = scenario_contract(scenario)
    total_budget = 50 if mode == "budget_matched" else None
    return {
        "case_id": "CASE-01",
        "repeat_index": repeat_index,
        "model": "test-model",
        "provider": "profile-test",
        "prompt_hash": f"prompt-{scenario}",
        "input_hash": "input-hash",
        "input_sha256": "input-sha256",
        "input_byte_length": 128,
        "input_artifact_sha256": "input-artifact-sha256",
        "input_artifact_byte_length": 129,
        "task_spec_hash": "task-hash",
        "runtime_task_spec_hash": f"runtime-{scenario}",
        "evaluation_spec_hash": "evaluation-hash",
        "evaluator_id": EXTERNAL_EVALUATOR_ID,
        "normalizer_id": MODEL_GRAPH_NORMALIZER_ID,
        "evaluation_owner": EXTERNAL_EVALUATOR_ID,
        "ground_truth_model_visible": False,
        "evaluation_boundary": {
            "model_visible": False,
            "ground_truth_payload_transmitted": False,
            "guard_enforced": True,
        },
        "temperature": 0.2,
        "benchmark_token_budget": 3000,
        "comparison_mode": mode,
        "total_output_token_budget": total_budget,
        "verifier_enabled": contract.verifier_enabled,
        "gate_enabled": contract.gate_enabled,
        "repair_enabled": contract.repair_enabled,
        "cas_enabled": contract.cas_enabled,
        "scenario": scenario,
        "repair_runtime_controls": {
            "structured_output_repair": contract.repair_enabled,
            "vertical_feedback": contract.repair_enabled,
            "automatic_operational_completion": contract.repair_enabled,
            "vertical_completion_bridge": contract.repair_enabled,
        },
        "graph_hash": f"graph-{scenario}-{repeat_index}",
        "execution_status": "completed",
        "metric_record": {
            "semantic.end_to_end_traceability": 0.5,
            "telemetry.estimated_cost_usd": 0.001,
        },
        "telemetry": {
            "call_count": 1,
            "repair_call_count": 0,
            "input_tokens": 8,
            "output_tokens": 12,
            "total_tokens": 20,
            "token_usage_status": "available",
            "provider_latency_ms": 5,
            "wall_latency_ms": 7,
            "cost_status": "available",
            "estimated_cost_usd": 0.001,
            "budget_within_cap": True,
        },
    }


@pytest.mark.parametrize(
    ("mode", "expected_budget"),
    (("natural", "not_applicable"), ("budget_matched", True)),
)
def test_comparison_aggregator_records_all_evidence_invariants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    expected_budget: bool,
) -> None:
    cases = (CASE,)
    observed_runtime_configs = []

    def fake_run_benchmark(*args, **kwargs):
        scenario = str(kwargs["scenario"])
        observed_runtime_configs.append(kwargs["runtime_config"])
        records = [_fake_comparison_record(scenario, index, mode) for index in range(1, 4)]
        return {
            "score": {"final_status": "ACCEPTED"},
            "metrics": {},
            "semantic_metrics": {"end_to_end_traceability": 0.5},
            "governance_metrics": {},
            "metadata": {"scenario_metadata": records},
        }

    monkeypatch.setattr(benchmark_runner_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(benchmark_runner_module, "load_cases", lambda _path: cases)
    monkeypatch.setattr(
        benchmark_runner_module,
        "_persisted_input_audit",
        lambda *args, **kwargs: {
            "checked_count": 15,
            "all_present": True,
            "all_exact": True,
            "records": [],
        },
    )

    comparison = benchmark_runner_module.run_scenario_comparison(
        Path("tests/mbse_benchmark/cases"),
        tmp_path / "output" / mode,
        repeats=3,
        report_dir=tmp_path / "report" / mode,
        profile="test-profile",
        runtime_config={
            "id": "profile-test",
            "provider": "openai-compatible",
            "model": "test-model",
        },
        comparison_mode=mode,
        total_output_token_budget=50 if mode == "budget_matched" else None,
    )

    assert comparison["same_model_provider"] is True
    assert comparison["same_input"] is True
    assert comparison["same_task_spec"] is True
    assert comparison["same_temperature"] is True
    assert comparison["call_budget_comparable"] is True
    assert comparison["ground_truth_isolated"] is True
    assert comparison["ablation_contract_valid"] is True
    assert comparison["repair_control_observed"] is True
    assert comparison["token_usage_observed"] is True
    assert comparison["latency_observed"] is True
    assert comparison["cost_observed"] is True
    assert comparison["budget_comparable"] == expected_budget
    assert comparison["budget_enforced"] == expected_budget
    assert {config["max_output_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["local_max_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["vertical_batch_output_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["vertical_singleton_output_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["remote_fail_fast"] for config in observed_runtime_configs} == {True}


def test_comparison_runtime_forces_real_provider_failures_to_fail_closed() -> None:
    shared, budget = _comparison_runtime_config({
        "model": "test-model",
        "max_output_tokens": 4096,
        "remote_fail_fast": False,
    })

    assert budget == 3000
    assert shared["remote_fail_fast"] is True


def test_budget_controls_are_persisted_on_successful_repeat_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    graph = {
        "project_id": "case-01",
        "revision": 0,
        "entities": [],
        "relations": [],
    }
    envelope = BenchmarkInputEnvelope.from_case(CASE)

    def fake_run_case(case, output_dir, *, repeat_index, **kwargs):
        del case, kwargs
        repeat_dir = output_dir / f"repeat_{repeat_index:02d}"
        repeat_dir.mkdir(parents=True, exist_ok=True)
        contract = scenario_contract(BenchmarkScenario.E_FULL_HARNESS)
        metadata = {
            "scenario": contract.scenario.value,
            "model": "test-model",
            "provider": "test-provider",
            "prompt_hash": "prompt",
            "task_spec_hash": "task",
            "temperature": 0.0,
            "input_hash": envelope.input_hash,
            "input_byte_length": len(envelope.canonical_bytes),
            "input_sha256": envelope.input_hash,
            "input_artifact_byte_length": len(envelope.canonical_bytes) + 1,
            "input_artifact_sha256": input_artifact_sha256(envelope),
            "benchmark_token_budget": 3000,
            "graph_hash": "graph",
            "verifier_enabled": True,
            "gate_enabled": True,
            "repair_enabled": True,
            "cas_enabled": True,
            "repair_runtime_controls": {
                "structured_output_repair": True,
                "vertical_feedback": True,
                "automatic_operational_completion": True,
                "vertical_completion_bridge": True,
            },
            "telemetry": {
                "call_count": 1,
                "repair_call_count": 0,
                "failed_call_count": 0,
                "input_tokens": 10,
                "output_tokens": 12,
                "total_tokens": 22,
                "token_usage_status": "available",
                "provider_latency_ms": 5,
                "wall_latency_ms": 7,
                "cost_status": "available",
                "estimated_cost_usd": 0.0,
                "budget_within_cap": True,
            },
        }
        return {
            "case_id": "CASE-01",
            "repeat_index": repeat_index,
            "output_dir": str(repeat_dir),
            "execution": {"status": "completed"},
            "graph": graph,
            "metadata": metadata,
        }

    monkeypatch.setattr(benchmark_runner_module, "run_case", fake_run_case)

    summary = run_benchmark(
        Path("tests/mbse_benchmark/cases"),
        tmp_path / "results",
        repeats=1,
        report_dir=tmp_path / "reports",
        selected_case="CASE-01",
        track="harness",
        scenario=BenchmarkScenario.E_FULL_HARNESS.value,
        comparison_mode="budget_matched",
        total_output_token_budget=50,
    )

    record = summary["metadata"]["scenario_metadata"][0]
    assert record["comparison_mode"] == "budget_matched"
    assert record["total_output_token_budget"] == 50


def test_comparison_rejects_hidden_repair_calls_in_disabled_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = (CASE,)

    def fake_run_benchmark(*args, **kwargs):
        scenario = str(kwargs["scenario"])
        records = [_fake_comparison_record(scenario, index, "natural") for index in range(1, 4)]
        if scenario == BenchmarkScenario.D_HARNESS_NO_REPAIR.value:
            records[0]["telemetry"]["repair_call_count"] = 1
        return {
            "score": {"final_status": "ACCEPTED"},
            "metrics": {},
            "semantic_metrics": {"end_to_end_traceability": 0.5},
            "governance_metrics": {},
            "metadata": {"scenario_metadata": records},
        }

    monkeypatch.setattr(benchmark_runner_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(benchmark_runner_module, "load_cases", lambda _path: cases)
    monkeypatch.setattr(
        benchmark_runner_module,
        "_persisted_input_audit",
        lambda *args, **kwargs: {
            "checked_count": 15,
            "all_present": True,
            "all_exact": True,
            "records": [],
        },
    )

    with pytest.raises(ValueError, match="repair_control_observed"):
        benchmark_runner_module.run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            tmp_path / "output",
            repeats=3,
            report_dir=tmp_path / "report",
            profile="test-profile",
            runtime_config={
                "id": "profile-test",
                "provider": "openai-compatible",
                "model": "test-model",
            },
        )


def test_comparison_rejects_mismatched_repair_runtime_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = (CASE,)

    def fake_run_benchmark(*args, **kwargs):
        scenario = str(kwargs["scenario"])
        records = [_fake_comparison_record(scenario, index, "natural") for index in range(1, 4)]
        if scenario == BenchmarkScenario.D_HARNESS_NO_REPAIR.value:
            records[0]["repair_runtime_controls"]["vertical_feedback"] = True
        return {
            "score": {"final_status": "ACCEPTED"},
            "metrics": {},
            "semantic_metrics": {"end_to_end_traceability": 0.5},
            "governance_metrics": {},
            "metadata": {"scenario_metadata": records},
        }

    monkeypatch.setattr(benchmark_runner_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(benchmark_runner_module, "load_cases", lambda _path: cases)
    monkeypatch.setattr(
        benchmark_runner_module,
        "_persisted_input_audit",
        lambda *args, **kwargs: {
            "checked_count": 15,
            "all_present": True,
            "all_exact": True,
            "records": [],
        },
    )

    with pytest.raises(ValueError, match="repair_control_observed"):
        benchmark_runner_module.run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            tmp_path / "output",
            repeats=3,
            report_dir=tmp_path / "report",
            profile="test-profile",
            runtime_config={
                "id": "profile-test",
                "provider": "openai-compatible",
                "model": "test-model",
            },
        )


def test_comparison_rejects_missing_temperature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = (CASE,)

    def fake_run_benchmark(*args, **kwargs):
        scenario = str(kwargs["scenario"])
        records = [_fake_comparison_record(scenario, index, "natural") for index in range(1, 4)]
        for record in records:
            record["temperature"] = None
        return {
            "score": {"final_status": "ACCEPTED"},
            "metrics": {},
            "semantic_metrics": {"end_to_end_traceability": 0.5},
            "governance_metrics": {},
            "metadata": {"scenario_metadata": records},
        }

    monkeypatch.setattr(benchmark_runner_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(benchmark_runner_module, "load_cases", lambda _path: cases)
    monkeypatch.setattr(
        benchmark_runner_module,
        "_persisted_input_audit",
        lambda *args, **kwargs: {
            "checked_count": 15,
            "all_present": True,
            "all_exact": True,
            "records": [],
        },
    )

    with pytest.raises(ValueError, match="comparison invariant"):
        benchmark_runner_module.run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            tmp_path / "output",
            repeats=3,
            report_dir=tmp_path / "report",
            profile="test-profile",
            runtime_config={
                "id": "profile-test",
                "provider": "openai-compatible",
                "model": "test-model",
            },
            comparison_mode="natural",
        )


def test_failed_repeat_is_excluded_from_quality_and_reported_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = (CASE,)

    def fake_run_benchmark(*args, **kwargs):
        scenario = str(kwargs["scenario"])
        records = [_fake_comparison_record(scenario, index, "natural") for index in range(1, 4)]
        if scenario == BenchmarkScenario.A_BARE_ONE_SHOT.value:
            records[0]["execution_status"] = "failed"
            records[0]["graph_hash"] = None
            records[0]["metric_record"]["semantic.end_to_end_traceability"] = 0.0
            records[0]["telemetry"]["failed_call_count"] = 1
        return {
            "score": {"final_status": "ACCEPTED"},
            "metrics": {},
            "semantic_metrics": {"end_to_end_traceability": 0.5},
            "governance_metrics": {},
            "metadata": {"scenario_metadata": records},
        }

    monkeypatch.setattr(benchmark_runner_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(benchmark_runner_module, "load_cases", lambda _path: cases)
    monkeypatch.setattr(
        benchmark_runner_module,
        "_persisted_input_audit",
        lambda *args, **kwargs: {
            "checked_count": 15,
            "all_present": True,
            "all_exact": True,
            "records": [],
        },
    )

    report_dir = tmp_path / "report"
    with pytest.raises(ValueError, match="execution_complete"):
        run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            tmp_path / "output",
            repeats=3,
            report_dir=report_dir,
            profile="test-profile",
            runtime_config={
                "id": "profile-test",
                "provider": "openai-compatible",
                "model": "test-model",
            },
        )

    comparison = json.loads(
        (report_dir / "a_to_e_comparison.json").read_text(encoding="utf-8")
    )
    scenario = comparison["scenarios"][BenchmarkScenario.A_BARE_ONE_SHOT.value]
    assert scenario["metadata"]["repeat_audit"] == {
        "expected_record_count": 3,
        "observed_record_count": 3,
        "completed_record_count": 2,
        "failed_record_count": 1,
        "usable_metric_record_count": 2,
        "cost_observation_count": 3,
        "status": "incomplete",
    }
    assert scenario["metadata"]["metric_statistics"]["semantic.end_to_end_traceability"]["count"] == 2
    point = next(
        item for item in comparison["quality_cost_points"]
        if item["scenario"] == BenchmarkScenario.A_BARE_ONE_SHOT.value
    )
    assert point["quality"] is None
    assert point["quality_count"] == 2
    assert point["quality_status"] == "incomplete"
    assert point["repeat_status"] == "incomplete"
