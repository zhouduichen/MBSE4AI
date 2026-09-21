from __future__ import annotations

from pathlib import Path

from tests.mbse_benchmark.runners.case_runner import _write_canonical_input
from tests.mbse_benchmark.runners.experiment_contract import BenchmarkInputEnvelope
from tests.mbse_benchmark.scenarios import BenchmarkScenario, scenario_contract


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
