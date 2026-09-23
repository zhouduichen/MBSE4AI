from __future__ import annotations

from pathlib import Path

import pytest

from tests.mbse_benchmark.runners.benchmark_runner import (
    _comparison_runtime_config,
    _persisted_input_audit,
    run_scenario_comparison,
)
from tests.mbse_benchmark.runners import benchmark_runner as benchmark_runner_module
from tests.mbse_benchmark.runners.case_runner import _write_canonical_input
from tests.mbse_benchmark.runners.experiment_contract import BenchmarkInputEnvelope
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
        "task_spec_hash": "task-hash",
        "runtime_task_spec_hash": f"runtime-{scenario}",
        "evaluation_spec_hash": "evaluation-hash",
        "evaluator_id": EXTERNAL_EVALUATOR_ID,
        "normalizer_id": MODEL_GRAPH_NORMALIZER_ID,
        "evaluation_owner": EXTERNAL_EVALUATOR_ID,
        "ground_truth_model_visible": False,
        "evaluation_boundary": {"model_visible": False},
        "temperature": 0.2,
        "benchmark_token_budget": 3000,
        "comparison_mode": mode,
        "total_output_token_budget": total_budget,
        "verifier_enabled": contract.verifier_enabled,
        "gate_enabled": contract.gate_enabled,
        "repair_enabled": contract.repair_enabled,
        "cas_enabled": contract.cas_enabled,
        "graph_hash": f"graph-{scenario}-{repeat_index}",
        "execution_status": "completed",
        "metric_record": {
            "semantic.end_to_end_traceability": 0.5,
            "telemetry.estimated_cost_usd": 0.001,
        },
        "telemetry": {
            "call_count": 1,
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
    assert comparison["token_usage_observed"] is True
    assert comparison["latency_observed"] is True
    assert comparison["cost_observed"] is True
    assert comparison["budget_comparable"] == expected_budget
    assert comparison["budget_enforced"] == expected_budget
    assert {config["max_output_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["local_max_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["vertical_batch_output_tokens"] for config in observed_runtime_configs} == {3000}
    assert {config["vertical_singleton_output_tokens"] for config in observed_runtime_configs} == {3000}


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
