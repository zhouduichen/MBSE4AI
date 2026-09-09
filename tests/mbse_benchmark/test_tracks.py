from __future__ import annotations

from tests.mbse_benchmark.tracks.harness import HARNESS_METRICS, compute_harness_metrics
from tests.mbse_benchmark.tracks.llm import LLM_METRICS, evaluate_bare_payload
from tests.mbse_benchmark.tracks.robustness import FAULTS, run_robustness_benchmark


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
