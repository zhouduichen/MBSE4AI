"""Run all cases, validate observed outputs, and write acceptance reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.mbse_benchmark.cases.loader import load_cases, load_expectations
from tests.mbse_benchmark.runners.case_runner import run_case
from tests.mbse_benchmark.runners.report_builder import (
    build_failures,
    compute_metrics,
    compute_score,
    write_reports,
)
from tests.mbse_benchmark.validators.case import validate_case


def _case_output_name(case_id: str) -> str:
    return case_id.casefold().replace("-", "_")


def run_benchmark(cases_dir: Path, output_root: Path, *, repeats: int = 3, timeout_seconds: int = 60, report_dir: Path | None = None, selected_case: str | None = None) -> dict[str, object]:
    cases = load_cases(cases_dir)
    expectations = load_expectations(cases_dir.parent / "expected")
    if selected_case:
        cases = tuple(case for case in cases if str(case["case_id"]) == selected_case)
        if not cases:
            raise ValueError(f"unknown case: {selected_case}")
    output_root.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, object]] = []
    for case in cases:
        case_id = str(case["case_id"])
        case_dir = output_root / _case_output_name(case_id)
        repeat_results = [
            run_case(case, case_dir, repeat_index=index, timeout_seconds=timeout_seconds)
            for index in range(1, max(1, repeats) + 1)
        ]
        primary = next((item for item in repeat_results if item.get("graph")), repeat_results[0])
        validation = validate_case(case, primary, expectations, repeats=repeat_results)
        validation["repeat_results"] = repeat_results
        (case_dir / "validation.json").write_text(
            __import__("rflp_lite.domain.canonical", fromlist=["canonical_json"]).canonical_json(validation) + "\n",
            encoding="utf-8",
        )
        case_results.append(validation)
    metrics = compute_metrics(case_results)
    score = compute_score(metrics, case_results)
    failures = build_failures(case_results)
    summary: dict[str, object] = {
        "test_date": datetime.now(timezone.utc).isoformat(),
        "commit": _git_value(["rev-parse", "HEAD"]),
        "branch": _git_value(["branch", "--show-current"]),
        "entrypoint": "build_v2_services -> ProjectService -> AnalysisService.run -> WorkflowRunner",
        "runtime": "RuleRuntime",
        "configuration": "offline runtime override; isolated workspace; no external model",
        "cases": [str(case["case_id"]) for case in cases],
        "repeats": max(1, repeats),
        "metrics": metrics,
        "score": score,
        "failures": failures,
        "case_results": case_results,
        "traceability_summary": "\n".join(f"{item.get('case_id', '')}: {item.get('metrics', {}).get('end_to_end_traceability', 0)} end-to-end coverage" for item in case_results),
        "requirement_quality_summary": "\n".join(f"{item.get('case_id', '')}: validity={item.get('metrics', {}).get('requirement_validity', 0)}, atomicity={item.get('metrics', {}).get('requirement_atomicity', 0)}, verifiability={item.get('metrics', {}).get('requirement_verifiability', 0)}" for item in case_results),
        "consistency_summary": "\n".join(f"{item.get('case_id', '')}: conflict_detection={item.get('metrics', {}).get('known_conflict_detection', 0)}" for item in case_results),
        "fault_injection_summary": next((str(item.get('details', {}).get('consistency', {})) for item in case_results if item.get('case_id') == "CASE-05"), "CASE-05 was not selected."),
        "iteration_summary": "\n".join(f"{item.get('case_id', '')}: iteration_signal={item.get('metrics', {}).get('iteration_signal', False)}" for item in case_results),
    }
    write_reports(summary, report_dir or output_root.parent / "reports")
    return summary


def _git_value(args: list[str]) -> str:
    import subprocess

    try:
        result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AI4MBSE MBSE benchmark")
    parser.add_argument("--case", dest="selected_case")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60, dest="timeout_seconds")
    parser.add_argument("--output-root", type=Path, default=Path("tests/mbse_benchmark/results"))
    parser.add_argument("--report-dir", type=Path, default=Path("tests/mbse_benchmark/reports"))
    args = parser.parse_args()
    summary = run_benchmark(
        Path("tests/mbse_benchmark/cases"),
        args.output_root,
        repeats=args.repeats,
        timeout_seconds=args.timeout_seconds,
        report_dir=args.report_dir,
        selected_case=args.selected_case,
    )
    print(f"FINAL STATUS: {summary['score']['final_status']}")
    print(f"Score: {summary['score']['score']} / 100")
    print(f"P0: {summary['score']['p0_passed']} / {summary['score']['p0_total']} passed")
    return 0 if summary["score"]["final_status"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
