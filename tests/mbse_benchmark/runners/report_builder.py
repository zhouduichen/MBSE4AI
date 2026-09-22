"""Aggregate validator results and render the required acceptance reports."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from rflp_lite.domain.canonical import canonical_json


TARGETS = {
    "stakeholder_coverage": 0.85,
    "lifecycle_coverage": 0.90,
    "scenario_recall": 0.85,
    "requirement_validity": 0.90,
    "requirement_atomicity": 0.85,
    "requirement_verifiability": 0.90,
    "upstream_traceability": 0.95,
    "use_case_activity_consistency": 0.90,
    "derived_requirement_precision": 0.80,
    "architecture_traceability": 0.90,
    "verification_coverage": 0.90,
    "end_to_end_traceability": 0.85,
    "orphan_element_rate": 0.05,
    "known_conflict_detection": 1.0,
    "unsupported_hard_assumption_rate": 0.05,
    "regression_stability": 0.85,
}


def _numeric_values(values: list[object], *, missing: float | None = None) -> float | None:
    numeric = [float(item) for item in values if isinstance(item, (int, float)) and not isinstance(item, bool)]
    return round(sum(numeric) / len(numeric), 6) if numeric else missing


def compute_metrics(case_results: list[Mapping[str, object]]) -> dict[str, object]:
    keys = tuple(TARGETS) + ("orphan_test_case_rate", "activity_branch_coverage")
    aggregate: dict[str, object] = {}
    per_case: dict[str, dict[str, object]] = {}
    for result in case_results:
        case_id = str(result.get("case_id", ""))
        metrics = result.get("metrics", {})
        metrics = dict(metrics) if isinstance(metrics, Mapping) else {}
        per_case[case_id] = metrics
    for key in keys:
        if key == "known_conflict_detection":
            values = [
                metrics.get(key)
                for result, metrics in zip(case_results, per_case.values())
                if result.get("details", {}).get("consistency", {}).get("expected_conflicts")
            ]
        else:
            values = [metrics.get(key) for metrics in per_case.values()]
        aggregate[key] = _numeric_values(values)
    aggregate["iteration_signal"] = any(bool(metrics.get("iteration_signal")) for metrics in per_case.values())
    aggregate["per_case"] = per_case
    semantic_per_case = {
        str(result.get("case_id", "")): dict(result.get("semantic_metrics", {}))
        for result in case_results
        if isinstance(result.get("semantic_metrics"), Mapping)
    }
    governance_per_case = {
        str(result.get("case_id", "")): dict(result.get("governance_metrics", {}))
        for result in case_results
        if isinstance(result.get("governance_metrics"), Mapping)
    }
    authority_counts = [
        float(item.get("authority_violation_count", 0) or 0)
        for item in governance_per_case.values()
    ]
    technical_results = [
        bool(item.get("technical_closure", {}).get("passed"))
        for item in governance_per_case.values()
        if isinstance(item.get("technical_closure"), Mapping)
    ]
    release_results = [
        bool(item.get("release_closure", {}).get("passed"))
        for item in governance_per_case.values()
        if isinstance(item.get("release_closure"), Mapping)
    ]
    aggregate["semantic_metrics"] = {
        "per_case": semantic_per_case,
        "trace_accuracy": _numeric_values([
            item.get("trace_accuracy") for item in semantic_per_case.values()
        ]),
        "RFLP_coverage": _numeric_values([
            item.get("RFLP_coverage") for item in semantic_per_case.values()
        ]),
    }
    aggregate["governance_metrics"] = {
        "per_case": governance_per_case,
        "authority_violation_count": int(sum(authority_counts)),
        "technical_closure_pass_rate": (
            sum(technical_results) / len(technical_results)
            if technical_results else None
        ),
        "release_closure_pass_rate": (
            sum(release_results) / len(release_results)
            if release_results else None
        ),
    }
    return aggregate


def _threshold_pass(key: str, value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if key in {"orphan_element_rate", "unsupported_hard_assumption_rate", "orphan_test_case_rate"}:
        return float(value) <= TARGETS.get(key, 0.05)
    return float(value) >= TARGETS.get(key, 0.0)


def compute_score(metrics: Mapping[str, object], case_results: list[Mapping[str, object]]) -> dict[str, object]:
    def value(key: str, default: float = 0.0) -> float:
        raw = metrics.get(key)
        return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else default

    requirement_quality = sum(
        1.0 if _threshold_pass("unsupported_hard_assumption_rate", value("unsupported_hard_assumption_rate", 1.0)) else 0.0
        for _ in [0]
    )
    requirement_quality = (
        min(1.0, value("requirement_validity"))
        + min(1.0, value("requirement_atomicity"))
        + min(1.0, value("requirement_verifiability"))
    ) / 3.0
    architecture_consistency = value("known_conflict_detection")
    p0_conflicts = [
        item for result in case_results
        for item in result.get("details", {}).get("consistency", {}).get("findings", ())
        if isinstance(item, Mapping) and str(item.get("test_id", "")) == "T10"
    ]
    if any(str(item.get("status", "")) != "PASS" for item in p0_conflicts):
        architecture_consistency = min(architecture_consistency, 0.0)
    iteration_impact = (1.0 if bool(metrics.get("iteration_signal")) else 0.0)
    category_scores = {
        "Stakeholder & Lifecycle": min(value("stakeholder_coverage"), value("lifecycle_coverage")),
        "Scenario Analysis": value("scenario_recall"),
        "Requirement Quality": requirement_quality,
        "Use Case & Activity": value("use_case_activity_consistency"),
        "Derived Requirements": 0.0 if metrics.get("derived_requirement_precision") is None else value("derived_requirement_precision"),
        "Traceability": min(value("upstream_traceability"), value("architecture_traceability"), value("end_to_end_traceability")),
        "Architecture Consistency": architecture_consistency,
        "Verification": value("verification_coverage"),
        "Iteration / Impact Analysis": iteration_impact,
    }
    weights = {
        "Stakeholder & Lifecycle": 10,
        "Scenario Analysis": 10,
        "Requirement Quality": 15,
        "Use Case & Activity": 10,
        "Derived Requirements": 10,
        "Traceability": 15,
        "Architecture Consistency": 10,
        "Verification": 10,
        "Iteration / Impact Analysis": 10,
    }
    score = round(sum(category_scores[key] * weights[key] for key in category_scores), 2)
    p0 = {
        "P0-01 weight conflict detected": value("known_conflict_detection") >= 1.0 and any(
            str(item.get("conflict_id", "")) == "weight-conflict" and item.get("detected") is True
            for result in case_results
            for item in result.get("details", {}).get("consistency", {}).get("conflict_signals", ())
        ),
        "P0-02 runtime conflict detected": value("known_conflict_detection") >= 1.0 and any(
            str(item.get("conflict_id", "")) == "runtime-conflict" and item.get("detected") is True
            for result in case_results
            for item in result.get("details", {}).get("consistency", {}).get("conflict_signals", ())
        ),
        "P0-03 upstream trace is not broadly broken": value("upstream_traceability") >= 0.95,
        "P0-04 no false satisfied architecture": all(
            not bool(result.get("details", {}).get("consistency", {}).get("false_satisfaction_signal"))
            for result in case_results
        ),
        "P0-05 verification traces requirements": value("verification_coverage") >= 0.90,
        "P0-06 failure feedback/iteration exists": any(
            bool(result.get("details", {}).get("consistency", {}).get("iteration_signal"))
            for result in case_results
        ),
    }
    p0_passed = sum(1 for item in p0.values() if item)
    return {
        "score": score,
        "current_capability_score": score,
        "full_target_capability_score": 100.0,
        "category_scores": category_scores,
        "category_weights": weights,
        "p0": p0,
        "p0_passed": p0_passed,
        "p0_total": len(p0),
        "final_status": "ACCEPTED" if score >= 80 and p0_passed == len(p0) else "REJECTED",
    }


def build_failures(case_results: list[Mapping[str, object]]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for result in case_results:
        for item in result.get("findings", ()):
            if not isinstance(item, Mapping) or str(item.get("status", "")) not in {"FAIL", "BLOCKED"}:
                continue
            failures.append(dict(item))
    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    failures.sort(key=lambda item: (severity_order.get(str(item.get("severity", "P3")), 9), str(item.get("case_id", "")), str(item.get("test_id", ""))))
    return failures


def _git_value(args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _status_by_test(case_results: list[Mapping[str, object]]) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    for result in case_results:
        for finding in result.get("findings", ()):
            if not isinstance(finding, Mapping):
                continue
            values.setdefault(str(finding.get("test_id", "")), []).append(str(finding.get("status", "")))
    return {key: "FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS" if statuses and all(status == "PASS" for status in statuses) else "NOT_IMPLEMENTED" for key, statuses in values.items()}


def _top_unique_failures(failures: list[Mapping[str, object]], limit: int = 10) -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in failures:
        key = (str(item.get("severity", "")), str(item.get("category", "")), str(item.get("root_cause", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def render_benchmark_report(summary: Mapping[str, object]) -> str:
    metrics = dict(summary.get("metrics", {}))
    score = dict(summary.get("score", {}))
    cases = list(summary.get("case_results", ()))
    test_status = _status_by_test(cases)
    lines = [
        "# AI4MBSE Benchmark Report",
        "",
        "## 1. Executive Summary",
        "",
        f"Track: **{summary.get('track', 'harness')}**",
        "",
        f"Track status: **{summary.get('track_status', 'NOT_RUN')}**",
        "",
        f"FINAL STATUS: **{score.get('final_status', 'REJECTED')}**",
        "",
        f"Score: **{score.get('score', 0)} / 100**",
        "",
        f"Current Capability Score: **{score.get('current_capability_score', score.get('score', 0))} / 100**",
        "",
        f"Full Target Capability Score: **{score.get('full_target_capability_score', 100.0)} / 100**",
        "",
        f"P0: **{score.get('p0_passed', 0)} / {score.get('p0_total', 0)} passed**",
        "",
        "## 2. Tested System",
        "",
        f"- commit: `{summary.get('commit', 'unknown')}`",
        f"- branch: `{summary.get('branch', 'unknown')}`",
        f"- entrypoint: `{summary.get('entrypoint', 'unknown')}`",
        f"- runtime/provider: `{summary.get('runtime', 'offline-rule')}`",
        f"- profile/provider/model: `{summary.get('model_profile', 'offline-rule')}` / `{summary.get('provider', 'offline')}` / `{summary.get('model', 'rule-runtime')}`",
        f"- methodology version: `{summary.get('methodology_version', '')}`",
        f"- prompt hash: `{summary.get('prompt_hash', '')}`",
        f"- task spec hash: `{summary.get('task_spec_hash', '')}`",
        f"- case/repeat: `{', '.join(str(item) for item in summary.get('cases', ()))}` / `{summary.get('repeats', '')}`",
        f"- test date: `{summary.get('test_date', '')}`",
        f"- configuration: `{summary.get('configuration', '')}`",
        "",
        "## 3. Benchmark Results",
        "",
        "| Test | Result | Score | Critical Issues |",
        "| ---- | ------ | ----: | --------------- |",
    ]
    for test_id in [f"T{index}" for index in range(1, 21)]:
        status = test_status.get(test_id, "NOT_IMPLEMENTED")
        lines.append(f"| {test_id} | {status} |  | {', '.join(item.get('category', '') for item in summary.get('failures', ()) if str(item.get('test_id', '')).split('/')[0] == test_id)} |")
    lines.extend(["", "## 4. Metrics", "", "| Metric | Observed | Target |", "| ------ | -------: | -----: |"])
    for key, target in TARGETS.items():
        observed = metrics.get(key)
        display = "N/A" if observed is None else f"{float(observed):.3f}"
        lines.append(f"| {key} | {display} | {target:.2f} |")
    lines.extend(["", "## 5. P0 Failures", ""])
    p0 = score.get("p0", {})
    if not any(not value for value in p0.values()):
        lines.append("None")
    else:
        for label, passed in p0.items():
            lines.append(f"- {'PASS' if passed else 'FAIL'}: {label}")
    lines.extend([
        "",
        "## 5a. Semantic Metrics",
        "",
        f"`{json.dumps(summary.get('semantic_metrics', metrics), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## 5b. Governance Metrics",
        "",
        f"`{json.dumps(summary.get('governance_metrics', {}), ensure_ascii=False, sort_keys=True)}`",
    ])
    lines.extend(["", "## 6. Traceability Analysis", "", str(summary.get("traceability_summary", "No traceability data.")), "", "## 7. Requirement Quality", "", str(summary.get("requirement_quality_summary", "No requirement quality data.")), "", "## 8. Cross-stage Consistency", "", str(summary.get("consistency_summary", "No cross-stage consistency data.")), "", "## 9. Fault Injection Result", "", str(summary.get("fault_injection_summary", "CASE-05 was not executed.")), "", "## 10. Iteration Test", "", str(summary.get("iteration_summary", "No iteration evidence.")), "", "## 11. Critical Problems", ""])
    failures = list(summary.get("failures", ()))
    top_failures = _top_unique_failures(failures)
    if top_failures:
        for item in top_failures:
            lines.append(f"- [{item.get('severity', 'P3')}] {item.get('case_id', '')} {item.get('test_id', '')}: {item.get('root_cause', '')}")
    else:
        lines.append("None")
    lines.extend(["", "## 12. Recommended Fix Order", "", "| Priority | Problem | Reason | Affected Module | Suggested Fix | Expected Benefit |", "| -------- | ------- | ------ | --------------- | ------------- | --------------- |"])
    for item in top_failures:
        lines.append(f"| {item.get('severity', 'P3')} | {item.get('category', '')} | {item.get('root_cause', '')} | current workflow | {item.get('recommended_fix', '')} | restores measurable MBSE coverage |")
    lines.extend(["", "## 13. Final Acceptance Decision", "", f"**{score.get('final_status', 'REJECTED')}**", ""])
    track_metrics = summary.get("track_metrics", {})
    if isinstance(track_metrics, Mapping):
        lines.extend(["", "## 14. Track-specific Metrics", "", "| Metric | Observed |", "| ------ | -------: |"])
        for key, value in track_metrics.items():
            if key == "per_case":
                continue
            lines.append(f"| {key} | {'N/A' if value is None else value} |")
    scenario_metadata = summary.get("metadata", {}).get("scenario_metadata", ()) if isinstance(summary.get("metadata", {}), Mapping) else ()
    if scenario_metadata:
        lines.extend(["", "## 15. Reproducibility Metadata", "", "| Scenario | Model | Provider | Input Hash | Graph Hash | Verifier | Gate | Repair | CAS |", "| -------- | ----- | -------- | ---------- | ---------- | -------- | ---- | ------ | --- |"])
        for item in scenario_metadata:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"| {item.get('scenario', '')} | {item.get('model', '')} | {item.get('provider', '')} | "
                f"`{item.get('input_hash', '')}` | `{item.get('graph_hash', '')}` | "
                f"{item.get('verifier_enabled', '')} | {item.get('gate_enabled', '')} | "
                f"{item.get('repair_enabled', '')} | {item.get('cas_enabled', '')} |"
            )
    return "\n".join(lines)


def render_traceability_report(summary: Mapping[str, object]) -> str:
    lines = ["# Traceability Report", "", "| Case | Requirement | Stakeholder | Scenario | Use Case | Activity | Function | Logical | Physical | Verification | Status |", "| ---- | ----------- | ----------- | -------- | -------- | -------- | -------- | ------- | -------- | ------------ | ------ |"]
    complete = partial = broken = 0
    for result in summary.get("case_results", ()):
        details = result.get("details", {}) if isinstance(result, Mapping) else {}
        trace = details.get("traceability", {}) if isinstance(details, Mapping) else {}
        paths = trace.get("trace_paths", {}) if isinstance(trace, Mapping) else {}
        complete_ids = set(trace.get("complete_requirement_ids", ())) if isinstance(trace, Mapping) else set()
        for requirement_id, path in paths.items() if isinstance(paths, Mapping) else ():
            values = {
                "Function": bool(path.get("function")),
                "Logical": bool(path.get("logical")),
                "Physical": bool(path.get("physical")),
                "Verification": requirement_id in set(trace.get("complete_requirement_ids", ())) if isinstance(trace, Mapping) else False,
            }
            if requirement_id in complete_ids:
                status = "Complete"
                complete += 1
            elif any(values.values()):
                status = "Partial"
                partial += 1
            else:
                status = "Broken"
                broken += 1
            def cell(value: object) -> str:
                return "N/A" if value is None else "PASS" if value else "FAIL"

            lines.append(f"| {result.get('case_id', '')} | {requirement_id} | {cell(trace.get('upstream_traceability'))} | {cell(trace.get('upstream_traceability'))} | {cell(trace.get('use_case_traceability'))} | {cell(trace.get('activity_traceability'))} | {cell(values['Function'])} | {cell(values['Logical'])} | {cell(values['Physical'])} | {cell(values['Verification'])} | {status} |")
    total = complete + partial + broken
    lines.extend(["", f"Complete Trace %: {complete / total:.3f}" if total else "Complete Trace %: N/A", f"Partial Trace %: {partial / total:.3f}" if total else "Partial Trace %: N/A", f"Broken Trace %: {broken / total:.3f}" if total else "Broken Trace %: N/A", "Orphan %: see benchmark metrics."])
    return "\n".join(lines) + "\n"


def _summary_text(summary: Mapping[str, object], key: str) -> str:
    values = []
    for result in summary.get("case_results", ()):
        details = result.get("details", {}) if isinstance(result, Mapping) else {}
        value = details.get(key, {}) if isinstance(details, Mapping) else {}
        if value:
            values.append(f"{result.get('case_id', '')}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(values) if values else "None"


def write_reports(summary: Mapping[str, object], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    benchmark = render_benchmark_report(summary)
    traceability = render_traceability_report(summary)
    (report_dir / "benchmark_report.md").write_text(benchmark, encoding="utf-8")
    (report_dir / "traceability_report.md").write_text(traceability, encoding="utf-8")
    (report_dir / "metrics.json").write_text(canonical_json({
        "metadata": summary.get("metadata", {}),
        "track": summary.get("track", "harness"),
        "track_status": summary.get("track_status", "NOT_RUN"),
        "metrics": summary.get("metrics", {}),
        "track_metrics": summary.get("track_metrics", {}),
        "score": summary.get("score", {}),
    }) + "\n", encoding="utf-8")
    (report_dir / "failures.json").write_text(canonical_json(summary.get("failures", [])) + "\n", encoding="utf-8")


def render_scenario_comparison(comparison: Mapping[str, object]) -> str:
    lines = [
        "# A–E Same-Model Benchmark Comparison",
        "",
        f"Status: **{comparison.get('status', 'not_recorded')}**",
        "",
        f"Same model/provider: **{comparison.get('same_model_provider', 'N/A')}**; same input bytes: **{comparison.get('same_input', 'N/A')}**; same task spec: **{comparison.get('same_task_spec', 'N/A')}**; same evaluator: **{comparison.get('same_evaluator', 'N/A')}**; same normalizer: **{comparison.get('same_normalizer', 'N/A')}**; same evaluation spec: **{comparison.get('same_evaluation_spec', 'N/A')}**; ground truth isolated: **{comparison.get('ground_truth_isolated', 'N/A')}**",
        "",
        f"Same temperature: **{comparison.get('same_temperature', 'N/A')}**; budget comparable: **{comparison.get('budget_comparable', 'N/A')}**; budget enforced: **{comparison.get('budget_enforced', 'N/A')}**; orthogonal ablations: **{comparison.get('ablation_contract_valid', 'N/A')}**; execution complete: **{comparison.get('execution_complete', 'N/A')}**; real calls: **{comparison.get('real_calls_observed', 'N/A')}**; token usage: **{comparison.get('token_usage_observed', 'N/A')}**; latency: **{comparison.get('latency_observed', 'N/A')}**; cost: **{comparison.get('cost_observed', 'N/A')}**",
        "",
        "| Scenario | Model | Provider | Input Hash | Eval Spec Hash | Task Spec Hash | Graph Hashes | Verifier | Gate | Repair | CAS | Calls | Tokens | Cost |",
        "| -------- | ----- | -------- | ---------- | -------------- | -------------- | ------------ | -------- | ---- | ------ | --- | ----- | ------ | ---- |",
    ]
    scenarios = comparison.get("scenarios", {})
    for scenario, payload in scenarios.items() if isinstance(scenarios, Mapping) else ():
        metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
        metadata = metadata if isinstance(metadata, Mapping) else {}
        graph_hashes = metadata.get("graph_hashes", ())
        telemetry = metadata.get("telemetry", {})
        telemetry = telemetry if isinstance(telemetry, Mapping) else {}
        lines.append(
            f"| {scenario} | {metadata.get('model', '')} | {metadata.get('provider', '')} | "
            f"{chr(96)}{metadata.get('input_hash', '')}{chr(96)} | {chr(96)}{metadata.get('evaluation_spec_hash', '')}{chr(96)} | "
            f"{chr(96)}{metadata.get('task_spec_hash', '')}{chr(96)} | "
            f"{chr(96)}{', '.join(str(item) for item in graph_hashes)}{chr(96)} | "
            f"{metadata.get('verifier_enabled', '')} | {metadata.get('gate_enabled', '')} | "
            f"{metadata.get('repair_enabled', '')} | {metadata.get('cas_enabled', '')} | "
            f"{telemetry.get('call_count', 'N/A')} | {telemetry.get('total_tokens', 'N/A')} | "
            f"{telemetry.get('estimated_cost_usd', 'N/A')} ({telemetry.get('cost_status', 'unavailable')}) |"
        )
    lines.extend(["", "## Run metadata", ""])
    for scenario, payload in scenarios.items() if isinstance(scenarios, Mapping) else ():
        metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
        metadata = metadata if isinstance(metadata, Mapping) else {}
        lines.append(
            f"- `{scenario}`: prompt_hash=`{metadata.get('prompt_hash', '')}`, "
            f"temperature={metadata.get('temperature', 'N/A')}, "
            f"comparison_mode={metadata.get('comparison_mode', 'natural')}, "
            f"benchmark_token_budget={metadata.get('benchmark_token_budget', 'N/A')}, "
            f"token_usage={metadata.get('token_usage', 'N/A')}, "
            f"latency_ms={metadata.get('latency_ms', 'N/A')}, "
            f"telemetry_statistics={metadata.get('telemetry_statistics', 'N/A')}, "
            f"metric_statistics={metadata.get('metric_statistics', 'N/A')}"
        )
    lines.extend(["", "## Semantic versus governance metrics", ""])
    for scenario, payload in scenarios.items() if isinstance(scenarios, Mapping) else ():
        metrics = payload.get("semantic_metrics", {}) if isinstance(payload, Mapping) else {}
        metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
        governance = payload.get("governance_metrics", {}) if isinstance(payload, Mapping) else {}
        lines.append(
            f"- `{scenario}` semantic: `{json.dumps(metrics, ensure_ascii=False, sort_keys=True)}`; "
            f"governance: `{json.dumps(governance, ensure_ascii=False, sort_keys=True)}`"
        )
    quality_cost = comparison.get("quality_cost_points", ())
    if isinstance(quality_cost, (list, tuple)):
        lines.extend(["", "## Quality-Cost", "", "| Scenario | Quality | Cost | Cost status |", "| -------- | -------: | ----: | ----------- |"])
        for point in quality_cost:
            if isinstance(point, Mapping):
                lines.append(
                    f"| {point.get('scenario', '')} | {point.get('quality', 'N/A')} | "
                    f"{point.get('cost', 'N/A')} | {point.get('cost_status', 'unavailable')} |"
                )
    return "\n".join(lines) + "\n"


def write_scenario_comparison(comparison: Mapping[str, object], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "a_to_e_comparison.md").write_text(
        render_scenario_comparison(comparison),
        encoding="utf-8",
    )
    (report_dir / "a_to_e_comparison.json").write_text(
        canonical_json(comparison) + "\n",
        encoding="utf-8",
    )
    manifest: list[dict[str, object]] = []
    scenarios = comparison.get("scenarios", {})
    if isinstance(scenarios, Mapping):
        for scenario, payload in scenarios.items():
            metadata = payload.get("metadata", {}) if isinstance(payload, Mapping) else {}
            records = metadata.get("repeat_records", ()) if isinstance(metadata, Mapping) else ()
            for record in records if isinstance(records, (list, tuple)) else ():
                if isinstance(record, Mapping):
                    manifest.append({"scenario": scenario, **dict(record)})
    (report_dir / "reproducibility_manifest.json").write_text(
        canonical_json({
            "track": comparison.get("track"),
            "profile": comparison.get("profile"),
            "same_model_provider": comparison.get("same_model_provider"),
            "same_input": comparison.get("same_input"),
            "same_task_spec": comparison.get("same_task_spec"),
            "same_evaluation_spec": comparison.get("same_evaluation_spec"),
            "same_evaluator": comparison.get("same_evaluator"),
            "same_normalizer": comparison.get("same_normalizer"),
            "ground_truth_isolated": comparison.get("ground_truth_isolated"),
            "same_temperature": comparison.get("same_temperature"),
            "budget_comparable": comparison.get("budget_comparable"),
            "budget_enforced": comparison.get("budget_enforced"),
            "comparison_mode": comparison.get("comparison_mode"),
            "total_output_token_budget": comparison.get("total_output_token_budget"),
            "ablation_contract_valid": comparison.get("ablation_contract_valid"),
            "execution_complete": comparison.get("execution_complete"),
            "real_calls_observed": comparison.get("real_calls_observed"),
            "token_usage_observed": comparison.get("token_usage_observed"),
            "latency_observed": comparison.get("latency_observed"),
            "cost_observed": comparison.get("cost_observed"),
            "input_artifact_audit": comparison.get("input_artifact_audit", {}),
            "records": manifest,
        }) + "\n",
        encoding="utf-8",
    )
