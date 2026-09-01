"""Executable customer-acceptance smoke harness for requirements and MBSE."""

from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.application.acceptance_gold import load_gold_contract
from rflp_lite.application.acceptance_metrics import (
    FORMAL_THRESHOLDS,
    evaluate_requirement_extraction,
    formal_acceptance_status,
)
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact


def run_customer_acceptance(
    filename: str, content: bytes, gold_path: Path | None = None
) -> dict[str, object]:
    state = analyze_artifact(filename, content)
    explicit = tuple(state.get("structured_requirements", ()))
    reviewed = accept_traceable(state)
    mbse_state = generate_mbse_revision(reviewed) if explicit else reviewed
    model = mbse_state.get("mbse") or {}
    report: dict[str, object] = {
        "document": {
            "parsed": bool(state.get("document_regions")),
            "pages": len(state.get("document_pages", ())),
            "regions": len(state.get("document_regions", ())),
        },
        "structured_requirements": {
            "count": len(explicit),
            "entities": len(state.get("entities", ())),
            "candidate_only": all(item.get("status") == "candidate" for item in explicit),
        },
        "traceability": state.get("trace_coverage", {}),
        "mbse": {
            "use_cases": len(model.get("use_cases", ())),
            "activities": len(model.get("activities", ())),
            "messages": len(model.get("messages", ())),
            "trace_links": len(model.get("trace_links", ())),
        },
    }
    if gold_path is not None:
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        source_text_by_region = {
            str(region.get("id", "")): str(region.get("text", ""))
            for region in state.get("document_regions", ())
            if isinstance(region, dict)
        }
        report["gold_version"] = gold.get("version", 1)
        report["formal_thresholds"] = dict(FORMAL_THRESHOLDS)
        contract = None
        try:
            if gold.get("version") == 3:
                contract = load_gold_contract(gold_path)
                report["gold_contract_status"] = "valid"
                effective_thresholds = dict(FORMAL_THRESHOLDS)
                for name, value in contract.thresholds.items():
                    if name in effective_thresholds:
                        effective_thresholds[name] = max(effective_thresholds[name], value)
                report["effective_thresholds"] = effective_thresholds
            else:
                report["gold_contract_status"] = "legacy_only"
        except ContractViolation as exc:
            report["gold_contract_status"] = "invalid"
            report["gold_contract_error"] = str(exc)

        if contract is not None:
            metrics = evaluate_requirement_extraction(
                explicit,
                contract.requirements,
                source_text_by_region=source_text_by_region,
                contract=contract,
            )
        else:
            expected_requirements = tuple(gold.get("requirements", ()))
            use_source_text = any(
                isinstance(item, dict) and "source_text" in item
                for item in expected_requirements
            )
            metric_items = []
            for item in explicit:
                metric_item = dict(item)
                source_region_id = str(metric_item.get("source_region_id", ""))
                if use_source_text and source_region_id in source_text_by_region:
                    metric_item["source_text"] = source_text_by_region[source_region_id]
                metric_items.append(metric_item)
            metrics = evaluate_requirement_extraction(metric_items, expected_requirements)
        report["extraction_metrics"] = metrics
        report["provenance_diagnostics"] = metrics.get("provenance_diagnostics", [])
        failures: list[str] = []
        if report.get("gold_contract_status") != "valid":
            failures.append("gold_contract_not_v3_complete")
        if report["gold_contract_status"] == "valid":
            effective = report["effective_thresholds"]
            if float(metrics.get("precision", 0.0)) < float(effective["requirement_precision"]):
                failures.append("requirement_precision")
            if float(metrics.get("recall", 0.0)) < float(effective["requirement_recall"]):
                failures.append("requirement_recall")
            if int(metrics.get("provenance_complete", 0)) < int(effective["provenance_complete"]):
                failures.append("provenance_complete")
            if "detail_micro_f1" in metrics and float(metrics["detail_micro_f1"]) < float(effective["detail_micro_f1"]):
                failures.append("detail_micro_f1")
            if metrics.get("unmatched_actual"):
                failures.append("unexpected_actual_requirements")
            if metrics.get("unmatched_expected"):
                failures.append("missing_expected_requirements")
        report["formal_failures"] = failures
    checks = {
        "1.1.document_capture": bool(report["document"]["parsed"]),
        "1.1.structured_mapping": bool(report["structured_requirements"]["count"]),
        "1.1.entity_extraction": bool(report["structured_requirements"]["entities"]),
        "1.1.traceability": report["traceability"].get("source_complete", 0) == 100,
        "1.2.use_case_model": bool(report["mbse"]["use_cases"]),
        "1.2.activity_model": bool(report["mbse"]["activities"]),
        "1.2.sequence_model": bool(report["mbse"]["messages"]),
        "1.2.model_traceability": bool(report["mbse"]["trace_links"]),
    }
    report["checks"] = checks
    report["smoke_status"] = "passed" if all(checks.values()) else "failed"
    if gold_path is None:
        report["formal_status"] = formal_acceptance_status(None)
    elif report.get("gold_contract_status") != "valid":
        report["formal_status"] = "failed"
    else:
        report["formal_status"] = "passed" if not report.get("formal_failures") else "failed"
    # Keep the original top-level field for existing CLI and API consumers,
    # while making a gold-backed run reflect the formal quality gate.
    report["status"] = (
        report["formal_status"]
        if gold_path is not None
        else report["smoke_status"]
    )
    return report
