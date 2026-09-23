"""Metrics specific to the deterministic RuleRuntime harness track."""

from __future__ import annotations

from typing import Any, Mapping


HARNESS_METRICS = (
    "pipeline_completion",
    "revision_determinism",
    "graph_hash_determinism",
    "rflp_trace_coverage",
    "gate_detection",
    "repair_recovery",
    "cas_lock_protection",
    "closure_manifest",
    "audit_completeness",
)


def _ledger(result: Mapping[str, object]) -> Mapping[str, object]:
    value = result.get("run_ledger", {})
    return value if isinstance(value, Mapping) else {}


def _repeat_signatures(results: list[Mapping[str, object]]) -> tuple[tuple[object, object], ...]:
    return tuple(
        (
            item.get("graph", {}).get("revision") if isinstance(item.get("graph"), Mapping) else None,
            item.get("graph", {}).get("snapshot_hash") if isinstance(item.get("graph"), Mapping) else None,
        )
        for item in results
    )


def _has_text(value: object, terms: tuple[str, ...]) -> bool:
    text = str(value).casefold()
    return any(term.casefold() in text for term in terms)


def _has_gate_recovery(audit_events: list[Mapping[str, object]]) -> bool:
    """Require repair, a fresh passing Gate, and issue resolution in order."""

    for index, event in enumerate(audit_events):
        if str(event.get("kind", "")).casefold() != "repair.applied":
            continue
        later = audit_events[index + 1:]
        passed_gate = any(
            str(item.get("kind", "")).casefold() == "gate.evaluated"
            and isinstance(item.get("payload"), Mapping)
            and item["payload"].get("passed") is True
            for item in later
        )
        resolved_issue = any(
            str(item.get("kind", "")).casefold() == "issue.resolved"
            for item in later
        )
        if passed_gate and resolved_issue:
            return True
    return False


def evaluate_harness_case(result: Mapping[str, object]) -> dict[str, object]:
    repeats = result.get("repeat_results", ())
    repeat_results = [item for item in repeats if isinstance(item, Mapping)]
    primary = next((item for item in repeat_results if item.get("graph")), result)
    summary = primary.get("run_summary", {})
    summary = summary if isinstance(summary, Mapping) else {}
    execution = primary.get("execution", {})
    execution = execution if isinstance(execution, Mapping) else {}
    graph = primary.get("graph", {})
    graph = graph if isinstance(graph, Mapping) else {}
    signatures = _repeat_signatures(repeat_results)
    complete_graphs = bool(repeat_results) and all(
        isinstance(item.get("graph"), Mapping) and bool(item.get("graph"))
        for item in repeat_results
    )
    completed = (
        execution.get("status") == "completed"
        and summary.get("status") in {"completed", "RunStatus.COMPLETED"}
        and isinstance(summary.get("closure"), Mapping)
        and summary.get("closure", {}).get("status") == "completed"
    )
    run_ledger = _ledger(primary)
    steps = run_ledger.get("steps", ())
    steps = steps if isinstance(steps, (list, tuple)) else ()
    audit = primary.get("audit", {})
    audit = audit if isinstance(audit, Mapping) else {}
    audit_events = audit.get("events", ()) if isinstance(audit, Mapping) else ()
    audit_events = audit_events if isinstance(audit_events, (list, tuple)) else ()
    gate_results = summary.get("gate_results", ())
    gate_results = gate_results if isinstance(gate_results, (list, tuple)) else ()
    traceability = result.get("details", {})
    traceability = traceability.get("traceability", {}) if isinstance(traceability, Mapping) else {}
    traceability = traceability if isinstance(traceability, Mapping) else {}
    coverage_matrix = primary.get("coverage_matrix", {})
    coverage_metrics = coverage_matrix.get("metrics", {}) if isinstance(coverage_matrix, Mapping) else {}
    coverage_metrics = coverage_metrics if isinstance(coverage_metrics, Mapping) else {}
    details = result.get("details", {})
    details = details if isinstance(details, Mapping) else {}
    consistency = details.get("consistency", {})
    consistency = consistency if isinstance(consistency, Mapping) else {}
    gate_evidence = [
        item for item in gate_results
        if isinstance(item, Mapping)
        and isinstance(item.get("passed"), bool)
        and (item.get("issues") or not item.get("passed"))
    ]
    repair_evidence = [
        item for item in audit_events
        if isinstance(item, Mapping)
        and str(item.get("kind", "")).casefold() in {"repair.applied", "task.recovered"}
    ]
    rflp_coverage = coverage_metrics.get(
        "r_to_f_to_l_to_p_coverage",
        traceability.get("architecture_traceability"),
    )
    return {
        "pipeline_completion": 1.0 if completed else 0.0,
        "revision_determinism": 1.0 if complete_graphs and len({item[0] for item in signatures}) <= 1 else 0.0,
        "graph_hash_determinism": 1.0 if complete_graphs and len({item[1] for item in signatures}) <= 1 else 0.0,
        "rflp_trace_coverage": rflp_coverage,
        "gate_detection": 1.0 if gate_evidence or consistency.get("conflict_signals") else 0.0,
        "repair_recovery": 1.0 if repair_evidence and _has_gate_recovery(audit_events) else 0.0,
        "cas_lock_protection": 1.0 if isinstance(primary.get("cas_probe"), Mapping) and primary["cas_probe"].get("stale_write_rejected") is True else 0.0,
        "closure_manifest": 1.0 if isinstance(summary.get("closure"), Mapping) and summary["closure"].get("manifest") else 0.0,
        "audit_completeness": 1.0 if run_ledger and steps and audit_events else 0.0,
        "repeat_count": len(repeat_results),
        "primary_revision": graph.get("revision"),
    }


def compute_harness_metrics(case_results: list[Mapping[str, object]]) -> dict[str, object]:
    per_case = {
        str(result.get("case_id", "")): evaluate_harness_case(result)
        for result in case_results
    }
    aggregate: dict[str, object] = {}
    for key in HARNESS_METRICS:
        values = [
            float(metrics[key])
            for metrics in per_case.values()
            if isinstance(metrics.get(key), (int, float)) and not isinstance(metrics.get(key), bool)
        ]
        aggregate[key] = round(sum(values) / len(values), 6) if values else None
    aggregate["per_case"] = per_case
    aggregate["repeat_minimum"] = min(
        (int(metrics.get("repeat_count", 0)) for metrics in per_case.values()),
        default=0,
    )
    return aggregate
