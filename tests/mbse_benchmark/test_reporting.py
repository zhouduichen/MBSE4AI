from __future__ import annotations

import json
from pathlib import Path

from tests.mbse_benchmark.runners.report_builder import (
    build_failures,
    compute_metrics,
    compute_score,
    write_reports,
    write_scenario_comparison,
)
from rflp_lite.methodology.coverage_status import coverage_result


def _case_result(case_id: str, *, p0_failure: bool = False) -> dict[str, object]:
    conflict_signals = []
    if case_id == "CASE-05":
        conflict_signals = [
            {"conflict_id": "weight-conflict", "detected": True},
            {"conflict_id": "runtime-conflict", "detected": True},
        ]
    details = {"consistency": {"findings": [], "conflict_signals": conflict_signals, "expected_conflicts": conflict_signals, "false_satisfaction_signal": False, "iteration_signal": True}}
    if p0_failure:
        details["consistency"]["findings"].append({"test_id": "T10", "status": "FAIL"})
    metrics = {
        "stakeholder_coverage": 1.0,
        "lifecycle_coverage": 1.0,
        "scenario_recall": 1.0,
        "requirement_validity": 1.0,
        "requirement_atomicity": 1.0,
        "requirement_verifiability": 1.0,
        "unsupported_hard_assumption_rate": 0.0,
        "upstream_traceability": 1.0,
        "use_case_activity_consistency": 1.0,
        "derived_requirement_precision": 1.0,
        "architecture_traceability": 1.0,
        "verification_coverage": 1.0,
        "end_to_end_traceability": 1.0,
        "orphan_element_rate": 0.0,
        "known_conflict_detection": 1.0,
        "regression_stability": 1.0,
        "iteration_signal": True,
    }
    return {"case_id": case_id, "metrics": metrics, "details": details, "findings": details["consistency"]["findings"]}


def test_metrics_and_score_accept_only_when_p0_is_clean() -> None:
    good = [_case_result("CASE-01"), _case_result("CASE-05")]
    metrics = compute_metrics(good)
    score = compute_score(metrics, good)

    assert score["score"] == 100.0
    assert score["final_status"] == "ACCEPTED"
    assert score["p0_passed"] == score["p0_total"]
    assert build_failures(good) == []


def test_report_writer_emits_required_files_and_rejects_p0_failure(tmp_path: Path) -> None:
    bad = [_case_result("CASE-01", p0_failure=True)]
    metrics = compute_metrics(bad)
    score = compute_score(metrics, bad)
    summary = {"metrics": metrics, "score": score, "failures": build_failures(bad), "case_results": bad}
    write_reports(summary, tmp_path)

    assert score["final_status"] == "REJECTED"
    assert (tmp_path / "benchmark_report.md").is_file()
    assert (tmp_path / "metrics.json").is_file()
    assert (tmp_path / "failures.json").is_file()
    assert (tmp_path / "traceability_report.md").is_file()
    assert json.loads((tmp_path / "failures.json").read_text(encoding="utf-8"))[0]["status"] == "FAIL"


def test_empty_coverage_is_not_applicable_and_reports_keep_the_value(tmp_path: Path) -> None:
    empty = coverage_result(0, 0)
    assert empty["coverage"] is None
    assert empty["status"] == "not_applicable"
    assert empty["passed"] is False

    write_reports({"metrics": {}, "score": {}, "case_results": []}, tmp_path)
    traceability = (tmp_path / "traceability_report.md").read_text(encoding="utf-8")
    assert "Complete Trace %: N/A" in traceability
    assert "1.0" not in traceability


def test_scenario_comparison_writes_reproducibility_manifest(tmp_path: Path) -> None:
    comparison = {
        "track": "llm_same_model_comparison",
        "profile": "test",
        "same_model_provider": True,
        "same_input": True,
        "same_task_spec": True,
        "scenarios": {
            "A": {
                "metadata": {
                    "repeat_records": [{"repeat_index": 1, "input_hash": "same"}],
                    "telemetry": {"call_count": 1, "total_tokens": 2},
                },
                "metrics": {},
            }
        },
        "quality_cost_points": [],
    }

    write_scenario_comparison(comparison, tmp_path)

    manifest = json.loads((tmp_path / "reproducibility_manifest.json").read_text(encoding="utf-8"))
    assert manifest["records"] == [{"scenario": "A", "repeat_index": 1, "input_hash": "same"}]
