from __future__ import annotations

import json
from pathlib import Path

from tests.mbse_benchmark.cases.loader import load_cases
from tests.mbse_benchmark.runners.case_runner import _run_case_inner
from tests.mbse_benchmark.tracks.harness import HARNESS_METRICS, compute_harness_metrics
from tests.mbse_benchmark.tracks.llm import LLM_METRICS, evaluate_bare_payload
from tests.mbse_benchmark.tracks.robustness import FAULTS, run_robustness_benchmark
from tests.mbse_benchmark.scenarios import BenchmarkScenario, evaluate_normalized, normalize_to_model_graph, scenario_contract


def test_harness_track_keeps_repeat_and_graph_determinism_metrics_separate() -> None:
    result = {
        "case_id": "CASE-01",
        "repeat_results": [
            {"repeat_index": 1, "execution": {"status": "completed"}, "graph": {"revision": 3, "snapshot_hash": "same"}, "run_summary": {"status": "completed", "closure": {"manifest": {}}}, "run_ledger": {"methodology_version": "v2.1", "steps": [{"task_id": "x"}]}, "audit": {"events": []}},
            {"repeat_index": 2, "execution": {"status": "completed"}, "graph": {"revision": 3, "snapshot_hash": "same"}, "run_summary": {"status": "completed"}, "run_ledger": {"methodology_version": "v2.1", "steps": [{"task_id": "x"}]}, "audit": {"events": []}},
            {"repeat_index": 3, "execution": {"status": "completed"}, "graph": {"revision": 3, "snapshot_hash": "same"}, "run_summary": {"status": "completed"}, "run_ledger": {"methodology_version": "v2.1", "steps": [{"task_id": "x"}]}, "audit": {"events": []}},
        ],
        "details": {"traceability": {"end_to_end_traceability": 1.0}, "consistency": {"conflict_signals": []}},
    }
    metrics = compute_harness_metrics([result])
    assert set(HARNESS_METRICS) <= metrics.keys()
    assert metrics["graph_hash_determinism"] == 1.0
    assert metrics["repeat_minimum"] == 3


def test_bare_llm_metrics_are_schema_level_and_do_not_claim_traceability() -> None:
    case = {"requirements": [{"id": "R1", "statement": "续航不少于 12 小时"}]}
    metrics = evaluate_bare_payload(case, {"requirements": [{"id": "R1", "statement": "续航不少于 12 小时", "verification_method": "test"}]})
    assert set(LLM_METRICS) <= metrics.keys()
    assert metrics["requirement_precision"] == 1.0
    assert metrics["RFLP_coverage"] == 0.0


def test_robustness_track_covers_required_faults_without_merging_into_harness_score() -> None:
    summary = run_robustness_benchmark()
    assert tuple(summary["faults"]) == FAULTS
    assert summary["metrics"]["detection_rate"] == 1.0
    locked = next(item for item in summary["case_results"] if item["fault_id"] == "locked_user_edit_conflict")
    assert locked["requires_human_review"] is True
    assert locked["repair_success"] is False


def test_benchmark_scenarios_have_explicit_capabilities_and_share_graph_normalization() -> None:
    assert scenario_contract(BenchmarkScenario.E_FULL_HARNESS).has_verifier is True
    assert scenario_contract(BenchmarkScenario.A_BARE_ONE_SHOT).has_cas is False
    graph = normalize_to_model_graph(
        {"requirements": [{"id": "R1", "statement": "续航不少于 12 小时"}]},
        project_id="scenario-a",
    )
    observed = evaluate_normalized(
        graph,
        lambda value: {"revision": value.revision, "requirement_count": len(value.entities)},
    )
    assert observed["graph"]["project_id"] == "scenario-a"
    assert observed["metrics"] == {"revision": 0, "requirement_count": 1}


def test_bare_scenario_executes_without_harness_controls(tmp_path) -> None:
    case = load_cases(Path("tests/mbse_benchmark/cases"))[0]
    output = tmp_path / "bare"
    _run_case_inner(
        case,
        output,
        scenario=BenchmarkScenario.A_BARE_ONE_SHOT.value,
    )

    execution = json.loads((output / "execution.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
    graph = json.loads((output / "model.json").read_text(encoding="utf-8"))
    assert execution["status"] == "completed"
    assert execution["scenario_controls"] == {
        "verifier": False,
        "repair": False,
        "cas": False,
    }
    assert execution["cas_probe"] == {}
    assert summary["closure"]["status"] == "blocked"
    assert any(item["kind"] == "verification_case" for item in graph["entities"])
    assert any(item["kind"] == "validation_case" for item in graph["entities"])
