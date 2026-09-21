"""Run all cases, validate observed outputs, and write acceptance reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

from tests.mbse_benchmark.cases.loader import load_cases, load_evaluation_spec
from tests.mbse_benchmark.runners.case_runner import run_case
from tests.mbse_benchmark.runners.report_builder import (
    build_failures,
    compute_metrics,
    compute_score,
    write_scenario_comparison,
    write_reports,
)
from tests.mbse_benchmark.tracks import BenchmarkTrack
from tests.mbse_benchmark.tracks.harness import compute_harness_metrics
from tests.mbse_benchmark.scenarios import (
    BenchmarkScenario,
    scenario_contract,
    validate_ablation_contracts,
)
from tests.mbse_benchmark.runners.scenario_pipeline import (
    EXTERNAL_EVALUATOR_ID,
    ExternalEvaluator,
    MODEL_GRAPH_NORMALIZER_ID,
    ModelGraphNormalizer,
)
from tests.mbse_benchmark.runners.experiment_contract import BenchmarkInputEnvelope
from tests.mbse_benchmark.runners.experiment_contract import (
    numeric_projection,
    summarize_repeats,
)


def _metric_display(value: object) -> object:
    return "N/A" if value is None else value


def _case_output_name(case_id: str) -> str:
    return case_id.casefold().replace("-", "_")


def _persisted_input_audit(
    output_root: Path,
    cases: tuple[Mapping[str, object], ...],
    *,
    repeats: int,
) -> dict[str, object]:
    """Verify the bytes actually written for every scenario/repeat.

    Metadata hashes are useful but not sufficient evidence: a runner could
    report the expected hash without writing those bytes to the model input
    file.  This audit reads only the canonical input artifacts and never
    exposes their payload in the comparison report.
    """

    records: list[dict[str, object]] = []
    repeat_count = max(1, int(repeats))
    for scenario in BenchmarkScenario:
        for case in cases:
            envelope = BenchmarkInputEnvelope.from_case(case)
            expected_bytes = envelope.canonical_bytes + b"\n"
            expected_file_hash = hashlib.sha256(expected_bytes).hexdigest()
            for repeat_index in range(1, repeat_count + 1):
                path = (
                    output_root
                    / scenario.value
                    / _case_output_name(envelope.case_id)
                    / f"repeat_{repeat_index:02d}"
                    / "input.json"
                )
                if not path.is_file():
                    records.append({
                        "scenario": scenario.value,
                        "case_id": envelope.case_id,
                        "repeat_index": repeat_index,
                        "path": str(path),
                        "present": False,
                        "exact": False,
                        "expected_sha256": expected_file_hash,
                        "observed_sha256": None,
                        "expected_byte_length": len(expected_bytes),
                        "observed_byte_length": None,
                    })
                    continue
                observed_bytes = path.read_bytes()
                records.append({
                    "scenario": scenario.value,
                    "case_id": envelope.case_id,
                    "repeat_index": repeat_index,
                    "path": str(path),
                    "present": True,
                    "exact": observed_bytes == expected_bytes,
                    "expected_sha256": expected_file_hash,
                    "observed_sha256": hashlib.sha256(observed_bytes).hexdigest(),
                    "expected_byte_length": len(expected_bytes),
                    "observed_byte_length": len(observed_bytes),
                })
    return {
        "checked_count": len(records),
        "all_present": bool(records) and all(bool(item["present"]) for item in records),
        "all_exact": bool(records) and all(bool(item["exact"]) for item in records),
        "records": records,
    }


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
    analysis_path: str = "lifecycle",
    scenario: str = BenchmarkScenario.E_FULL_HARNESS.value,
    comparison_mode: str = "natural",
    total_output_token_budget: int | None = None,
    evaluator: ExternalEvaluator | None = None,
) -> dict[str, object]:
    if track not in {item.value for item in BenchmarkTrack if item is not BenchmarkTrack.ROBUSTNESS}:
        raise ValueError(f"run_benchmark only executes harness or llm tracks: {track}")
    if track == BenchmarkTrack.LLM.value and not runtime_config:
        raise ValueError("runtime_config is required for the explicit llm track")
    if analysis_path not in {"lifecycle", "vertical"}:
        raise ValueError(f"unknown analysis path: {analysis_path}")
    if analysis_path == "vertical" and track != BenchmarkTrack.LLM.value:
        raise ValueError("the vertical analysis path is only available on the explicit llm track")
    contract = scenario_contract(scenario)
    validate_ablation_contracts()
    normalizer = evaluator.normalizer if evaluator is not None else ModelGraphNormalizer()
    evaluator = evaluator or ExternalEvaluator(normalizer)
    cases = load_cases(cases_dir)
    evaluation_spec = load_evaluation_spec(cases_dir.parent / "expected")
    if selected_case:
        cases = tuple(case for case in cases if str(case["case_id"]) == selected_case)
        if not cases:
            raise ValueError(f"unknown case: {selected_case}")
    output_root.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, object]] = []
    for case in cases:
        case_id = str(case["case_id"])
        input_envelope = BenchmarkInputEnvelope.from_case(case)
        case_dir = output_root / _case_output_name(case_id)
        repeat_results = [
            run_case(
                case,
                case_dir,
                repeat_index=index,
                timeout_seconds=timeout_seconds,
                runtime_config=runtime_config,
                analysis_path=analysis_path,
                scenario=contract.scenario.value,
                comparison_mode=comparison_mode,
                total_output_token_budget=total_output_token_budget,
            )
            for index in range(1, max(1, repeats) + 1)
        ]
        is_bare = contract.scenario in {
            BenchmarkScenario.A_BARE_ONE_SHOT,
            BenchmarkScenario.B_BARE_STAGED,
        }
        for repeat_result in repeat_results:
            metadata = repeat_result.get("metadata")
            if isinstance(metadata, Mapping):
                metadata["evaluation_spec_hash"] = evaluation_spec.evaluation_spec_hash
                metadata["case_id"] = case_id
                metadata["repeat_index"] = repeat_result.get("repeat_index")
            graph = (
                normalizer.normalize(
                    repeat_result.get("graph", {}),
                    project_id=case_id.lower(),
                )
                if is_bare
                else normalizer.normalize_canonical(
                    repeat_result.get("graph", {}),
                    project_id=case_id.lower(),
                )
            )
            repeat_result["graph"] = normalizer.payload(graph)
            if isinstance(metadata, Mapping):
                repeat_result["normalization_audit"] = metadata.get(
                    "normalization_audit",
                    {},
                )
                for control_key in (
                    "verifier_enabled",
                    "gate_enabled",
                    "repair_enabled",
                    "cas_enabled",
                ):
                    repeat_result[control_key] = metadata.get(control_key)
                execution = repeat_result.get("execution", {})
                metadata["execution_status"] = (
                    execution.get("status")
                    if isinstance(execution, Mapping)
                    else None
                )
                metadata["evaluator_id"] = evaluator.evaluator_id
                metadata["normalizer_id"] = normalizer.normalizer_id
            repeat_validation = evaluator.evaluate(
                input_envelope,
                graph,
                evaluation_spec,
                raw_result=repeat_result,
            )
            repeat_result["metrics"] = dict(
                repeat_validation.get(
                    "semantic_metrics",
                    repeat_validation.get("metrics", {}),
                )
            )
            repeat_result["semantic_metrics"] = dict(
                repeat_validation.get("semantic_metrics", {})
            )
            repeat_result["governance_metrics"] = dict(
                repeat_validation.get("governance_metrics", {})
            )
            repeat_result["input_hash"] = input_envelope.input_hash
            repeat_result["evaluation_spec_hash"] = evaluation_spec.evaluation_spec_hash
            metric_record = _repeat_metric_record(
                repeat_validation,
                telemetry=metadata.get("telemetry", {})
                if isinstance(metadata, Mapping)
                else {},
            )
            repeat_result["metric_record"] = metric_record
            if isinstance(metadata, Mapping):
                metadata["semantic_metrics"] = repeat_result["semantic_metrics"]
                metadata["governance_metrics"] = repeat_result["governance_metrics"]
                metadata["metric_record"] = metric_record
        primary = next((item for item in repeat_results if item.get("graph")), repeat_results[0])
        graph = normalizer.normalize_canonical(
            primary.get("graph", {}),
            project_id=case_id.lower(),
        )
        primary["graph"] = normalizer.payload(graph)
        validation = evaluator.evaluate(
            input_envelope,
            graph,
            evaluation_spec,
            raw_result=primary,
            repeats=repeat_results,
        )
        validation["repeat_results"] = repeat_results
        validation["repeat_statistics"] = summarize_repeats([
            item.get("metric_record", {})
            for item in repeat_results
            if isinstance(item.get("metric_record"), Mapping)
        ])
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
        "entrypoint": (
            "build_v2_services -> ProjectService -> ModelGenerationService.generate -> five-stage vertical path"
            if analysis_path == "vertical"
            else "build_v2_services -> ProjectService -> AnalysisService.run -> WorkflowRunner"
        ),
        "analysis_path": analysis_path,
        "scenario": contract.scenario.value,
        "scenario_contract": {
            "description": contract.description,
            "generation_shape": contract.generation_shape,
            "verifier_enabled": contract.verifier_enabled,
            "gate_enabled": contract.gate_enabled,
            "repair_enabled": contract.repair_enabled,
            "cas_enabled": contract.cas_enabled,
        },
        "runtime": "RuleRuntime" if track == BenchmarkTrack.HARNESS.value else "configured-llm",
        "model_profile": profile or "offline-rule",
        "provider": str(runtime_config.get("provider_id", runtime_config.get("provider", "offline"))) if runtime_config else "offline",
        "model": str(runtime_config.get("model", "rule-runtime")) if runtime_config else "rule-runtime",
        "methodology_version": "v2.1",
        "prompt_hash": ledger_metadata["prompt_hash"],
        "task_spec_hash": ledger_metadata["task_spec_hash"],
        "evaluation_spec_hash": evaluation_spec.evaluation_spec_hash,
        "evaluator_id": evaluator.evaluator_id,
        "normalizer_id": normalizer.normalizer_id,
        "configuration": "offline RuleRuntime; isolated workspace; no external model" if track == BenchmarkTrack.HARNESS.value else "explicit LLM profile; isolated workspace; provider credentials are not written to reports",
        "cases": [str(case["case_id"]) for case in cases],
        "repeats": max(1, repeats),
        "comparison_mode": comparison_mode,
        "total_output_token_budget": total_output_token_budget,
        "metrics": metrics,
        "semantic_metrics": metrics.get("semantic_metrics", {}),
        "governance_metrics": metrics.get("governance_metrics", {}),
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
            "evaluation_spec_hash": evaluation_spec.evaluation_spec_hash,
            "commit": _git_value(["rev-parse", "HEAD"]),
            "cases": [str(case["case_id"]) for case in cases],
            "repeat": max(1, repeats),
            "comparison_mode": comparison_mode,
            "total_output_token_budget": total_output_token_budget,
            "scenario_metadata": [
                item.get("metadata", {})
                for result in case_results
                for item in result.get("repeat_results", ())
                if isinstance(item, Mapping) and item.get("metadata")
            ],
        },
        "traceability_summary": "\n".join(f"{item.get('case_id', '')}: {_metric_display(item.get('metrics', {}).get('end_to_end_traceability'))} end-to-end coverage" for item in case_results),
        "requirement_quality_summary": "\n".join(f"{item.get('case_id', '')}: validity={_metric_display(item.get('metrics', {}).get('requirement_validity'))}, atomicity={_metric_display(item.get('metrics', {}).get('requirement_atomicity'))}, verifiability={_metric_display(item.get('metrics', {}).get('requirement_verifiability'))}" for item in case_results),
        "consistency_summary": "\n".join(f"{item.get('case_id', '')}: conflict_detection={_metric_display(item.get('metrics', {}).get('known_conflict_detection'))}" for item in case_results),
        "fault_injection_summary": next((str(item.get('details', {}).get('consistency', {})) for item in case_results if item.get('case_id') == "CASE-05"), "CASE-05 was not selected."),
        "iteration_summary": "\n".join(f"{item.get('case_id', '')}: iteration_signal={item.get('metrics', {}).get('iteration_signal', False)}" for item in case_results),
    }
    write_reports(summary, report_dir or output_root.parent / "reports")
    return summary


def run_scenario_comparison(
    cases_dir: Path,
    output_root: Path,
    *,
    repeats: int = 3,
    timeout_seconds: int = 60,
    report_dir: Path,
    selected_case: str | None = None,
    profile: str,
    runtime_config: Mapping[str, object],
    analysis_path: str = "lifecycle",
    comparison_mode: str = "natural",
    total_output_token_budget: int | None = None,
) -> dict[str, object]:
    """Run A–E with one resolved model configuration and one evaluator path."""

    if int(repeats) < 3:
        raise ValueError("A–E comparison requires at least three repeats")
    validate_ablation_contracts()
    shared_evaluator = ExternalEvaluator()
    scenario_summaries: dict[str, Mapping[str, object]] = {}
    for scenario in BenchmarkScenario:
        scenario_summaries[scenario.value] = run_benchmark(
            cases_dir,
            output_root / scenario.value,
            repeats=repeats,
            timeout_seconds=timeout_seconds,
            report_dir=report_dir / scenario.value,
            selected_case=selected_case,
            track=BenchmarkTrack.LLM.value,
            profile=profile,
            runtime_config=runtime_config,
            analysis_path=analysis_path,
            scenario=scenario.value,
            comparison_mode=comparison_mode,
            total_output_token_budget=total_output_token_budget,
            evaluator=shared_evaluator,
        )
    comparison: dict[str, object] = {
        "status": "recorded",
        "track": "llm_same_model_comparison",
        "profile": profile,
        "model": str(runtime_config.get("model", "")),
        "provider": str(runtime_config.get("provider_id", runtime_config.get("provider", ""))),
        "comparison_mode": comparison_mode,
        "total_output_token_budget": total_output_token_budget,
        "scenarios": {},
    }
    for scenario, summary in scenario_summaries.items():
        metadata = summary.get("metadata", {})
        run_metadata = metadata.get("scenario_metadata", ()) if isinstance(metadata, Mapping) else ()
        records = [item for item in run_metadata if isinstance(item, Mapping)]
        first = records[0] if records else {}
        comparison["scenarios"][scenario] = {
            "status": summary.get("score", {}).get("final_status", "NOT_RUN"),
            "metrics": summary.get("metrics", {}),
            "semantic_metrics": summary.get("semantic_metrics", {}),
            "governance_metrics": summary.get("governance_metrics", {}),
            "metadata": {
                "model": first.get("model", summary.get("model", "")),
                "provider": first.get("provider", summary.get("provider", "")),
                "prompt_hash": first.get("prompt_hash"),
                "input_hash": first.get("input_hash"),
                "input_sha256": first.get("input_sha256"),
                "input_byte_length": first.get("input_byte_length"),
                "task_spec_hash": first.get("task_spec_hash"),
                "evaluation_spec_hash": first.get("evaluation_spec_hash"),
                "evaluator_id": first.get("evaluator_id", EXTERNAL_EVALUATOR_ID),
                "normalizer_id": first.get("normalizer_id", MODEL_GRAPH_NORMALIZER_ID),
                "temperature": first.get("temperature"),
                "benchmark_token_budget": first.get("benchmark_token_budget"),
                "token_usage": first.get("token_usage"),
                "latency_ms": first.get("latency_ms"),
                "telemetry": first.get("telemetry", {}),
                "telemetry_statistics": summarize_repeats([
                    item.get("telemetry", {})
                    for item in records
                    if isinstance(item.get("telemetry"), Mapping)
                ]),
                "metric_statistics": summarize_repeats([
                    item.get("metric_record", {})
                    for item in records
                    if isinstance(item.get("metric_record"), Mapping)
                ]),
                "repeat_records": records,
                "semantic_metrics": summary.get("semantic_metrics", {}),
                "governance_metrics": summary.get("governance_metrics", {}),
                "comparison_mode": first.get("comparison_mode", comparison_mode),
                "total_output_token_budget": first.get(
                    "total_output_token_budget",
                    total_output_token_budget,
                ),
                "graph_hashes": [item.get("graph_hash") for item in records if item.get("graph_hash")],
                "execution_statuses": [item.get("execution_status") for item in records],
                "verifier_enabled": first.get("verifier_enabled"),
                "gate_enabled": first.get("gate_enabled"),
                "repair_enabled": first.get("repair_enabled"),
                "cas_enabled": first.get("cas_enabled"),
            },
        }
    comparison["controls"] = {
        scenario: {
            "verifier_enabled": scenario_contract(scenario).verifier_enabled,
            "gate_enabled": scenario_contract(scenario).gate_enabled,
            "repair_enabled": scenario_contract(scenario).repair_enabled,
            "cas_enabled": scenario_contract(scenario).cas_enabled,
        }
        for scenario in scenario_summaries
    }
    records_by_scenario = {
        scenario: [
            item
            for item in (
                payload.get("metadata", {}).get("repeat_records", ())
                if isinstance(payload, Mapping)
                and isinstance(payload.get("metadata"), Mapping)
                else ()
            )
            if isinstance(item, Mapping)
        ]
        for scenario, payload in comparison["scenarios"].items()
    }
    selected_cases = load_cases(cases_dir)
    if selected_case:
        selected_cases = tuple(
            case for case in selected_cases if str(case["case_id"]) == selected_case
        )
    comparison["input_artifact_audit"] = _persisted_input_audit(
        output_root,
        selected_cases,
        repeats=repeats,
    )
    all_records = [
        record
        for records in records_by_scenario.values()
        for record in records
    ]
    comparison["same_model_provider"] = bool(all_records) and len({
        (item.get("model"), item.get("provider")) for item in all_records
    }) == 1 and all(
        item.get("model") and item.get("provider") for item in all_records
    )
    input_sets = [
        tuple(sorted(
            (
                str(item.get("case_id", "")),
                int(item.get("repeat_index", 0) or 0),
                str(item.get("input_hash", "")),
                str(item.get("input_sha256", "")),
                int(item.get("input_byte_length", 0) or 0),
            )
            for item in records
        ))
        for records in records_by_scenario.values()
    ]
    comparison["same_input"] = (
        bool(input_sets)
        and len(set(input_sets)) == 1
        and bool(input_sets[0])
        and bool(comparison["input_artifact_audit"].get("all_exact"))
        and all(
            signature[2] and signature[3] and signature[4] > 0
            for signature in input_sets[0]
        )
    )
    comparison["same_task_spec"] = bool(all_records) and len({
        item.get("task_spec_hash") for item in all_records
    }) == 1 and all(item.get("task_spec_hash") for item in all_records)
    comparison["same_evaluation_spec"] = bool(all_records) and len({
        item.get("evaluation_spec_hash") for item in all_records
    }) == 1 and all(item.get("evaluation_spec_hash") for item in all_records)
    comparison["same_evaluator"] = bool(all_records) and len({
        item.get("evaluator_id") for item in all_records
    }) == 1 and all(item.get("evaluator_id") for item in all_records)
    comparison["same_normalizer"] = bool(all_records) and len({
        item.get("normalizer_id") for item in all_records
    }) == 1 and all(item.get("normalizer_id") for item in all_records)
    comparison["same_temperature"] = bool(all_records) and len({
        item.get("temperature") for item in all_records
    }) == 1
    modes = {str(item.get("comparison_mode", comparison_mode)) for item in all_records}
    if comparison_mode == "budget_matched":
        budgets = {item.get("total_output_token_budget") for item in all_records}
        comparison["budget_comparable"] = bool(all_records) and modes == {comparison_mode} and len(budgets) == 1 and None not in budgets
    else:
        budgets = {item.get("benchmark_token_budget") for item in all_records}
        comparison["budget_comparable"] = bool(all_records) and modes == {comparison_mode} and len(budgets) == 1 and None not in budgets
    comparison["ablation_contract_valid"] = all(
        all(
            all(record.get(key) == expected.get(key) for key in expected)
            for record in records_by_scenario.get(scenario, ())
        )
        for scenario, expected in comparison["controls"].items()
    )
    comparison["execution_complete"] = bool(all_records) and all(
        record.get("execution_status") == "completed"
        and bool(record.get("graph_hash"))
        for record in all_records
    )
    comparison["real_calls_observed"] = bool(all_records) and all(
        isinstance(record.get("telemetry"), Mapping)
        and int(record["telemetry"].get("call_count", 0) or 0) > 0
        for record in all_records
    )
    comparison["token_usage_observed"] = bool(all_records) and all(
        isinstance(record.get("telemetry"), Mapping)
        and record["telemetry"].get("token_usage_status") == "available"
        for record in all_records
    )
    comparison["quality_cost_points"] = [
        {
            "scenario": scenario,
            "quality": _stat_mean(
                payload.get("metadata", {}).get("metric_statistics", {})
                if isinstance(payload.get("metadata"), Mapping)
                else {},
                "semantic.end_to_end_traceability",
            ),
            "cost": _stat_mean(
                payload.get("metadata", {}).get("telemetry_statistics", {})
                if isinstance(payload.get("metadata"), Mapping)
                else {},
                "estimated_cost_usd",
            ),
            "cost_status": _cost_status(
                payload.get("metadata", {}).get("repeat_records", ())
                if isinstance(payload.get("metadata"), Mapping)
                else (),
            ),
        }
        for scenario, payload in comparison["scenarios"].items()
    ]
    if not all(
        comparison[key]
        for key in (
            "same_model_provider",
            "same_input",
            "same_task_spec",
            "same_evaluation_spec",
            "same_evaluator",
            "same_normalizer",
            "same_temperature",
            "budget_comparable",
            "ablation_contract_valid",
            "execution_complete",
            "real_calls_observed",
            "token_usage_observed",
        )
    ):
        raise ValueError("A–E comparison invariant failed: model, input, task, or evaluator differs")
    write_scenario_comparison(comparison, report_dir)
    return comparison


def _stat_mean(statistics: object, key: str) -> float | None:
    if not isinstance(statistics, Mapping):
        return None
    value = statistics.get(key)
    if not isinstance(value, Mapping):
        return None
    mean_value = value.get("mean")
    return float(mean_value) if isinstance(mean_value, (int, float)) else None


def _cost_status(records: object) -> str:
    statuses = {
        str(item.get("telemetry", {}).get("cost_status", "unavailable"))
        for item in records
        if isinstance(item, Mapping)
        and isinstance(item.get("telemetry"), Mapping)
    }
    if statuses == {"available"}:
        return "available"
    if len(statuses) > 1:
        return "mixed"
    return next(iter(statuses), "unavailable")


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
    run_metadata = [
        item.get("metadata", {})
        for item in repeat_results
        if isinstance(item.get("metadata"), Mapping)
    ]
    return {
        "track": track,
        "case": case_id,
        "profile": profile or "offline-rule",
        "repeat": [int(item.get("repeat_index", 0)) for item in repeat_results],
        "methodology_version": sorted({str(item.get("methodology_version", "")) for item in ledgers if item.get("methodology_version")}),
        "prompt_hash": sorted({str(item.get("prompt_hash", "")) for item in ledgers if item.get("prompt_hash")}),
        "task_spec_hash": sorted({str(item.get("task_spec_hash", "")) for item in ledgers if item.get("task_spec_hash")}),
        "evaluation_spec_hash": sorted({str(item.get("evaluation_spec_hash", "")) for item in run_metadata if item.get("evaluation_spec_hash")}),
        "run_metadata": run_metadata,
    }


def _repeat_metric_record(
    validation: Mapping[str, object],
    *,
    telemetry: Mapping[str, object],
) -> dict[str, float]:
    """Create one flat numeric record for semantic/governance/cost statistics."""

    record: dict[str, float] = {}
    semantic = validation.get("semantic_metrics", {})
    governance = validation.get("governance_metrics", {})
    if isinstance(semantic, Mapping):
        record.update(numeric_projection(semantic, prefix="semantic"))
    if isinstance(governance, Mapping):
        record.update(numeric_projection(governance, prefix="governance"))
        for key in ("technical_closure", "release_closure"):
            closure = governance.get(key, {})
            if isinstance(closure, Mapping):
                record[f"governance.{key}.passed"] = float(
                    bool(closure.get("passed"))
                )
    record.update(numeric_projection(telemetry, prefix="telemetry"))
    return record


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
    parser.add_argument("--compare-a-e", action="store_true", help="run A–E with one configured model and one evaluator")
    parser.add_argument("--comparison-mode", choices=("natural", "budget_matched"), default="natural")
    parser.add_argument("--total-output-token-budget", type=int)
    parser.add_argument(
        "--path",
        dest="analysis_path",
        choices=("lifecycle", "vertical"),
        default="lifecycle",
        help="analysis path; vertical runs the five-stage product generation path",
    )
    parser.add_argument("--scenario", choices=[item.value for item in BenchmarkScenario], default=BenchmarkScenario.E_FULL_HARNESS.value)
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
        if args.compare_a_e:
            comparison = run_scenario_comparison(
                Path("tests/mbse_benchmark/cases"),
                args.output_root,
                repeats=args.repeats,
                timeout_seconds=args.timeout_seconds,
                report_dir=args.report_dir,
                selected_case=args.selected_case,
                profile=args.profile,
                runtime_config=runtime_config,
                analysis_path=args.analysis_path,
                comparison_mode=args.comparison_mode,
                total_output_token_budget=args.total_output_token_budget,
            )
            print(f"A-E STATUS: {comparison['status']}")
            print(f"Scenarios: {', '.join(str(item) for item in comparison['scenarios'])}")
            return 0
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
        analysis_path=args.analysis_path,
        scenario=args.scenario,
        comparison_mode=args.comparison_mode,
        total_output_token_budget=args.total_output_token_budget,
    )
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
