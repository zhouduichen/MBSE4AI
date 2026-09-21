from __future__ import annotations

from pathlib import Path

import pytest

from tests.mbse_benchmark.runners.benchmark_runner import (
    _persisted_input_audit,
    run_scenario_comparison,
)
from tests.mbse_benchmark.runners.case_runner import _write_canonical_input
from tests.mbse_benchmark.runners.experiment_contract import BenchmarkInputEnvelope
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
