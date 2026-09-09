"""Run all cases, validate observed outputs, and write acceptance reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tests.mbse_benchmark.cases.loader import load_cases, load_expectations
from tests.mbse_benchmark.runners.case_runner import run_case
from tests.mbse_benchmark.runners.report_builder import (
    build_failures,
    compute_metrics,
    compute_score,
    write_reports,
)
from tests.mbse_benchmark.validators.case import validate_case
from tests.mbse_benchmark.tracks import BenchmarkTrack
from tests.mbse_benchmark.tracks.harness import compute_harness_metrics


def _case_output_name(case_id: str) -> str:
    return case_id.casefold().replace("-", "_")


def run_benchmark(
    cases_dir: Path,
    output_root: Path,
    *,
    repeats: int = 3,
    timeout_seconds: int = 60,
    report_dir: Path | None = None,
    selected_case: str | None = None,
    track: str = BenchmarkTrack.HARNESS.value,
    profile: str | None = None,
    runtime_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if track not in {item.value for item in BenchmarkTrack if item is not BenchmarkTrack.ROBUSTNESS}:
        raise ValueError(f"run_benchmark only executes harness or llm tracks: {track}")
    if track == BenchmarkTrack.LLM.value and not runtime_config:
        raise ValueError("runtime_config is required for the explicit llm track")
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
            run_case(
                case,
                case_dir,
                repeat_index=index,
                timeout_seconds=timeout_seconds,
                runtime_config=runtime_config,
            )
            for index in range(1, max(1, repeats) + 1)
        ]
        primary = next((item for item in repeat_results if item.get("graph")), repeat_results[0])
        validation = validate_case(case, primary, expectations, repeats=repeat_results)
        validation["repeat_results"] = repeat_results
        validation["metadata"] = _case_metadata(case_id, repeat_results, track=track, profile=profile)
        (case_dir / "validation.json").write_text(
            __import__("rflp_lite.domain.canonical", fromlist=["canonical_json"]).canonical_json(validation) + "\n",
            encoding="utf-8",
        )
        case_results.append(validation)
    metrics = compute_metrics(case_results)
    score = compute_score(metrics, case_results)
    failures = build_failures(case_results)
    ledger_metadata = _ledger_metadata(case_results)
    track_metrics = compute_harness_metrics(case_results)
    summary: dict[str, object] = {
        "track": track,
        "test_date": datetime.now(timezone.utc).isoformat(),
        "commit": _git_value(["rev-parse", "HEAD"]),
        "branch": _git_value(["branch", "--show-current"]),
        "entrypoint": "build_v2_services -> ProjectService -> AnalysisService.run -> WorkflowRunner",
        "runtime": "RuleRuntime" if track == BenchmarkTrack.HARNESS.value else "configured-llm",
        "model_profile": profile or "offline-rule",
        "provider": str(runtime_config.get("provider_id", runtime_config.get("provider", "offline"))) if runtime_config else "offline",
        "model": str(runtime_config.get("model", "rule-runtime")) if runtime_config else "rule-runtime",
        "methodology_version": "v2.1",
        "prompt_hash": ledger_metadata["prompt_hash"],
        "task_spec_hash": ledger_metadata["task_spec_hash"],
        "configuration": "offline RuleRuntime; isolated workspace; no external model" if track == BenchmarkTrack.HARNESS.value else "explicit LLM profile; isolated workspace; provider credentials are not written to reports",
        "cases": [str(case["case_id"]) for case in cases],
        "repeats": max(1, repeats),
        "metrics": metrics,
        "score": score,
        "failures": failures,
        "case_results": case_results,
        "track_metrics": track_metrics,
        "track_status": _harness_status(track_metrics) if track == BenchmarkTrack.HARNESS.value else "EXPLICIT",
        "metadata": {
            "track": track,
            "runtime": "RuleRuntime" if track == BenchmarkTrack.HARNESS.value else "configured-llm",
            "profile": profile or "offline-rule",
            "provider": str(runtime_config.get("provider_id", runtime_config.get("provider", "offline"))) if runtime_config else "offline",
            "model": str(runtime_config.get("model", "rule-runtime")) if runtime_config else "rule-runtime",
            "methodology_version": "v2.1",
            "prompt_hash": ledger_metadata["prompt_hash"],
            "task_spec_hash": ledger_metadata["task_spec_hash"],
            "commit": _git_value(["rev-parse", "HEAD"]),
            "cases": [str(case["case_id"]) for case in cases],
            "repeat": max(1, repeats),
        },
        "traceability_summary": "\n".join(f"{item.get('case_id', '')}: {item.get('metrics', {}).get('end_to_end_traceability', 0)} end-to-end coverage" for item in case_results),
        "requirement_quality_summary": "\n".join(f"{item.get('case_id', '')}: validity={item.get('metrics', {}).get('requirement_validity', 0)}, atomicity={item.get('metrics', {}).get('requirement_atomicity', 0)}, verifiability={item.get('metrics', {}).get('requirement_verifiability', 0)}" for item in case_results),
        "consistency_summary": "\n".join(f"{item.get('case_id', '')}: conflict_detection={item.get('metrics', {}).get('known_conflict_detection', 0)}" for item in case_results),
        "fault_injection_summary": next((str(item.get('details', {}).get('consistency', {})) for item in case_results if item.get('case_id') == "CASE-05"), "CASE-05 was not selected."),
        "iteration_summary": "\n".join(f"{item.get('case_id', '')}: iteration_signal={item.get('metrics', {}).get('iteration_signal', False)}" for item in case_results),
    }
    write_reports(summary, report_dir or output_root.parent / "reports")
    return summary


def _case_metadata(
    case_id: str,
    repeat_results: list[Mapping[str, object]],
    *,
    track: str,
    profile: str | None,
) -> dict[str, object]:
    ledgers = [
        item.get("run_ledger", {})
        for item in repeat_results
        if isinstance(item.get("run_ledger"), Mapping)
    ]
    return {
        "track": track,
        "case": case_id,
        "profile": profile or "offline-rule",
        "repeat": [int(item.get("repeat_index", 0)) for item in repeat_results],
        "methodology_version": sorted({str(item.get("methodology_version", "")) for item in ledgers if item.get("methodology_version")}),
        "prompt_hash": sorted({str(item.get("prompt_hash", "")) for item in ledgers if item.get("prompt_hash")}),
        "task_spec_hash": sorted({str(item.get("task_spec_hash", "")) for item in ledgers if item.get("task_spec_hash")}),
    }


def _ledger_metadata(case_results: list[Mapping[str, object]]) -> dict[str, str]:
    prompt_hashes: set[str] = set()
    task_spec_hashes: set[str] = set()
    for case in case_results:
        metadata = case.get("metadata", {})
        if not isinstance(metadata, Mapping):
            continue
        prompt_hashes.update(str(item) for item in metadata.get("prompt_hash", ()) if str(item))
        task_spec_hashes.update(str(item) for item in metadata.get("task_spec_hash", ()) if str(item))
    return {
        "prompt_hash": ",".join(sorted(prompt_hashes)),
        "task_spec_hash": ",".join(sorted(task_spec_hashes)),
    }


def _harness_status(metrics: Mapping[str, object]) -> str:
    required = (
        "pipeline_completion",
        "revision_determinism",
        "graph_hash_determinism",
        "rflp_trace_coverage",
        "gate_detection",
        "cas_lock_protection",
        "closure_manifest",
        "audit_completeness",
    )
    stable = all(float(metrics.get(key, 0.0) or 0.0) >= 1.0 for key in required)
    has_recovery = float(metrics.get("repair_recovery", 0.0) or 0.0) > 0.0
    return "PASS" if stable and has_recovery and int(metrics.get("repeat_minimum", 0) or 0) >= 3 else "FAIL"


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
    parser.add_argument("--track", choices=[item.value for item in BenchmarkTrack], default=BenchmarkTrack.HARNESS.value)
    parser.add_argument("--profile", help="explicit LLM profile ID; required by --track llm")
    parser.add_argument("--baseline", choices=("harness", "bare", "both"), default="both", help="LLM track comparison baseline")
    args = parser.parse_args()
    if args.track == BenchmarkTrack.ROBUSTNESS.value:
        from tests.mbse_benchmark.tracks.robustness import run_robustness_benchmark
        from tests.mbse_benchmark.tracks.robustness import write_robustness_report

        summary = run_robustness_benchmark()
        write_robustness_report(summary, args.report_dir / "robustness")
        print(f"FINAL STATUS: {summary['status']}")
        print(f"Detection rate: {summary['metrics']['detection_rate']:.3f}")
        return 0 if summary["status"] == "PASS" else 1
    runtime_config = None
    if args.track == BenchmarkTrack.LLM.value:
        from tests.mbse_benchmark.tracks.llm import resolve_profile

        if not args.profile:
            parser.error("--profile is required for --track llm")
        try:
            runtime_config = resolve_profile(args.profile)
        except ValueError as exc:
            parser.error(str(exc))
        args.output_root = args.output_root / "llm" / str(args.profile)
        args.report_dir = args.report_dir / "llm" / str(args.profile)
    summary = run_benchmark(
        Path("tests/mbse_benchmark/cases"),
        args.output_root,
        repeats=args.repeats,
        timeout_seconds=args.timeout_seconds,
        report_dir=args.report_dir,
        selected_case=args.selected_case,
        track=args.track,
        profile=args.profile,
        runtime_config=runtime_config,
    )
    if args.track == BenchmarkTrack.LLM.value and args.baseline in {"bare", "both"}:
        from tests.mbse_benchmark.tracks.llm import run_bare_baseline

        cases = load_cases(Path("tests/mbse_benchmark/cases"))
        if args.selected_case:
            cases = tuple(case for case in cases if str(case["case_id"]) == args.selected_case)
        summary["bare_llm_baseline"] = run_bare_baseline(cases, runtime_config or {})
        write_reports(summary, args.report_dir)
    print(f"FINAL STATUS: {summary['score']['final_status']}")
    if args.track == BenchmarkTrack.HARNESS.value:
        print(f"TRACK STATUS: {summary['track_status']}")
    print(f"Score: {summary['score']['score']} / 100")
    print(f"P0: {summary['score']['p0_passed']} / {summary['score']['p0_total']} passed")
    if args.track == BenchmarkTrack.HARNESS.value:
        return 0 if summary["track_status"] == "PASS" else 1
    return 0 if summary["score"]["final_status"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
