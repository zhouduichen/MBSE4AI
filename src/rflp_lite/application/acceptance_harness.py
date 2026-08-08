"""Executable customer-acceptance smoke harness for requirements and MBSE."""

from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.application.acceptance_metrics import evaluate_requirement_extraction
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
        report["extraction_metrics"] = evaluate_requirement_extraction(
            explicit, gold.get("requirements", ())
        )
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
    report["status"] = "passed" if all(checks.values()) else "failed"
    return report

