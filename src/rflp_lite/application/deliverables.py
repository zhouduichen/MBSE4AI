"""Revision-bound engineering deliverables derived from one ModelGraph."""

from __future__ import annotations

from io import BytesIO
import zipfile
from collections.abc import Mapping

from rflp_lite.application.projections.assurance import build_assurance_view
from rflp_lite.application.projections.requirements import build_requirements_view
from rflp_lite.application.projections.rflp import build_rflp_view
from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.application.sysml_v2 import graph_to_sysml
from rflp_lite.diagrams.engineering.rflp import render_rflp_svg
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.engine import MethodologyEngine
from rflp_lite.methodology.vv_contract import missing_vv_plan_fields


DELIVERABLE_FORMAT = "ai4mbse.engineering-deliverable.v1"
REQUIRED_MEMBERS = (
    "manifest.json",
    "model.json",
    "evidence.json",
    "model.sysml",
    "requirements.json",
    "rflp.json",
    "rflp.svg",
    "traceability.json",
    "vv-plan.json",
    "vv-plan.md",
    "architecture-report.json",
    "architecture-report.md",
)
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class EngineeringDeliverableService:
    """Compose user-facing engineering outputs without creating new model state."""

    def __init__(self, model_service, evidence_repository=None):
        self.model_service = model_service
        self.evidence_repository = evidence_repository

    def build(self, project_id: str) -> Mapping[str, object]:
        graph = self.model_service.graph(project_id)
        issues = tuple(self.model_service.issues(project_id))
        requirements = dict(build_requirements_view(graph, issues))
        rflp = dict(build_rflp_view(graph, issues))
        traceability = dict(build_traceability_view(graph, issues))
        assurance = dict(build_assurance_view(graph, issues))
        vv_plan = _vv_plan(assurance)
        methodology = MethodologyEngine().analyze(graph)
        architecture_report = _architecture_report(
            graph, rflp, traceability, assurance, vv_plan, methodology
        )
        evidence = _evidence_content(graph, self.evidence_repository)
        model = _model_content(graph, evidence=evidence["records"])
        artifacts = {
            "model": _artifact("model-json-v1", model, graph),
            "evidence": _artifact("evidence-json-v1", evidence, graph),
            "sysml": _artifact("sysml-v2-subset", graph_to_sysml(graph), graph),
            "requirements": _artifact("requirements-view-v1", requirements, graph),
            "rflp": _artifact("rflp-view-v1", rflp, graph),
            "rflp_svg": _artifact("rflp-svg-v1", render_rflp_svg(rflp), graph),
            "traceability": _artifact("traceability-view-v1", traceability, graph),
            "vv_plan": _artifact("vv-plan-v1", vv_plan, graph),
            "architecture_report": _artifact("architecture-report-v1", architecture_report, graph),
        }
        manifest = {
            "format": DELIVERABLE_FORMAT,
            "project_id": graph.project_id,
            "revision": graph.revision,
            "snapshot_hash": graph.snapshot_hash,
            "artifacts": {
                name: {
                    "format": str(artifact["format"]),
                    "path": _artifact_path(name),
                }
                for name, artifact in artifacts.items()
            },
        }
        return {
            "format": DELIVERABLE_FORMAT,
            "project_id": graph.project_id,
            "revision": graph.revision,
            "snapshot_hash": graph.snapshot_hash,
            "manifest": manifest,
            "artifacts": artifacts,
        }

    def export_zip(self, project_id: str) -> tuple[bytes, str]:
        package = self.build(project_id)
        artifacts = package["artifacts"]
        vv_plan = artifacts["vv_plan"]["content"]
        architecture_report = artifacts["architecture_report"]["content"]
        contents: dict[str, bytes] = {
            "manifest.json": _json_bytes(package["manifest"]),
            "model.json": _json_bytes(artifacts["model"]["content"]),
            "evidence.json": _json_bytes(artifacts["evidence"]["content"]),
            "model.sysml": str(artifacts["sysml"]["content"]).encode("utf-8"),
            "requirements.json": _json_bytes(artifacts["requirements"]["content"]),
            "rflp.json": _json_bytes(artifacts["rflp"]["content"]),
            "rflp.svg": str(artifacts["rflp_svg"]["content"]).encode("utf-8"),
            "traceability.json": _json_bytes(artifacts["traceability"]["content"]),
            "vv-plan.json": _json_bytes(vv_plan),
            "vv-plan.md": _vv_markdown(vv_plan).encode("utf-8"),
            "architecture-report.json": _json_bytes(architecture_report),
            "architecture-report.md": _architecture_markdown(architecture_report).encode("utf-8"),
        }
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for member in REQUIRED_MEMBERS:
                info = zipfile.ZipInfo(member, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o600 << 16
                archive.writestr(info, contents[member])
        return output.getvalue(), "application/zip"


def _artifact(format_id: str, content: object, graph: ModelGraph) -> Mapping[str, object]:
    return {
        "format": format_id,
        "project_id": graph.project_id,
        "revision": graph.revision,
        "snapshot_hash": graph.snapshot_hash,
        "content": content,
    }


def _artifact_path(name: str) -> str:
    return {
        "model": "model.json",
        "evidence": "evidence.json",
        "sysml": "model.sysml",
        "requirements": "requirements.json",
        "rflp": "rflp.json",
        "rflp_svg": "rflp.svg",
        "traceability": "traceability.json",
        "vv_plan": "vv-plan.json",
        "architecture_report": "architecture-report.json",
    }[name]


def _model_content(
    graph: ModelGraph,
    *,
    evidence: tuple[Mapping[str, object], ...] = (),
) -> Mapping[str, object]:
    return {
        "project_id": graph.project_id,
        "revision": graph.revision,
        "snapshot_hash": graph.snapshot_hash,
        "entities": [entity.as_dict() for entity in graph.entities],
        "relations": [
            {
                "id": relation.id,
                "source_id": relation.source_id,
                "predicate": relation.predicate.value,
                "target_id": relation.target_id,
                "evidence_ids": list(relation.evidence_ids),
            }
            for relation in graph.relations
        ],
        "evidence": [dict(item) for item in evidence],
    }


def _evidence_content(
    graph: ModelGraph,
    repository,
) -> Mapping[str, object]:
    """Snapshot project evidence alongside the graph's stable evidence IDs."""

    records = ()
    list_evidence = getattr(repository, "list_evidence", None)
    if callable(list_evidence):
        records = tuple(
            dict(item)
            for item in list_evidence(graph.project_id)
            if isinstance(item, Mapping) and str(item.get("id", "")).strip()
        )
    records = tuple(sorted(records, key=lambda item: str(item["id"])))
    return {
        "project_id": graph.project_id,
        "revision": graph.revision,
        "snapshot_hash": graph.snapshot_hash,
        "evidence_hash": canonical_hash(records),
        "records": [dict(item) for item in records],
    }


def _vv_plan(assurance: Mapping[str, object]) -> Mapping[str, object]:
    rows = []
    for raw in assurance.get("verification_validation", ()):
        row = dict(raw)
        missing: list[str] = []
        case_type = str(row.get("case_type", ""))
        case_id = row.get("case_id")
        if not case_id:
            missing.append(case_type)
        else:
            missing.extend(missing_vv_plan_fields(row))
        if row.get("status") != "PASS" and case_id:
            row["status"] = "INCOMPLETE"
        row["missing"] = missing
        rows.append(row)
    case_order = {"verification": 0, "validation": 1}
    rows.sort(key=lambda item: (
        str(item.get("requirement_id", "")),
        case_order.get(str(item.get("case_type", "")), 2),
        str(item.get("case_id", "")),
    ))
    gates = list(assurance.get("gates", ()))
    gate_metrics = dict(gates[-1].get("coverage_summary", {})) if gates else {}
    requirement_ids = {str(row.get("requirement_id", "")) for row in rows if row.get("requirement_id")}
    verification_rows = [row for row in rows if row.get("case_type") == "verification"]
    validation_rows = [row for row in rows if row.get("case_type") == "validation"]
    metrics = {
        "requirement_count": len(requirement_ids),
        "row_count": len(rows),
        "pass_row_count": sum(row.get("status") == "PASS" for row in rows),
        "incomplete_row_count": sum(row.get("status") != "PASS" for row in rows),
        "verification_coverage_percent": _coverage_percent(requirement_ids, verification_rows),
        "validation_coverage_percent": _coverage_percent(requirement_ids, validation_rows),
        "gate_coverage": gate_metrics,
    }
    return {"rows": rows, "gates": gates, "metrics": metrics}


def _coverage_percent(requirement_ids: set[str], rows: list[Mapping[str, object]]) -> float:
    if not requirement_ids:
        return 100.0
    covered = {
        str(row.get("requirement_id"))
        for row in rows
        if row.get("case_id")
    }
    return round(len(covered & requirement_ids) / len(requirement_ids) * 100, 2)


def _architecture_report(
    graph: ModelGraph,
    rflp: Mapping[str, object],
    traceability: Mapping[str, object],
    assurance: Mapping[str, object],
    vv_plan: Mapping[str, object],
    methodology,
) -> Mapping[str, object]:
    counts = {
        kind.value: sum(entity.kind is kind for entity in graph.entities)
        for kind in EntityKind
    }
    edges = list(rflp.get("edges", ()))
    valid_edges = sum(bool(edge.get("valid_for_trace")) for edge in edges)
    gates = list(assurance.get("gates", ()))
    gate_passed = bool(gates) and all(bool(gate.get("passed")) for gate in gates)
    has_blocking_issue = any(bool(gate.get("blocking_issues")) for gate in gates)
    trace_gaps = list(rflp.get("gaps", ()))
    vv_gaps = [
        row for row in vv_plan.get("rows", ())
        if str(row.get("status", "")) != "PASS"
    ]
    complete = gate_passed and not trace_gaps and not vv_gaps
    status = "PASS" if complete else "BLOCKED" if has_blocking_issue or trace_gaps or vv_gaps else "DEGRADED"
    methodology_metrics = dict(methodology.metrics)
    architecture = methodology_metrics.get("architecture_synthesis", {})
    architecture = dict(architecture) if isinstance(architecture, Mapping) else {}
    decision_metric_names = (
        "logical_partition_quality",
        "logical_timing_constraint_count",
        "logical_timing_cut_count",
        "logical_safety_isolation_count",
        "logical_safety_violation_count",
        "logical_safety_review_required",
        "physical_feasibility",
        "physical_conflict_count",
        "physical_unknown_field_count",
    )
    return {
        "status": status,
        "entity_counts": counts,
        "traceability_metrics": dict(traceability.get("metrics", {})),
        "valid_trace_edge_count": valid_edges,
        "invalid_trace_edge_count": len(edges) - valid_edges,
        "allocation_count": sum(
            relation.predicate.value == "allocatedTo" for relation in graph.relations
        ),
        "gates": gates,
        "gaps": trace_gaps,
        "vv_gaps": vv_gaps,
        "methodology_metrics": {
            key: methodology_metrics[key]
            for key in decision_metric_names
            if key in methodology_metrics
        },
        "architecture_synthesis": architecture,
    }


def _json_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _vv_markdown(vv_plan: Mapping[str, object]) -> str:
    lines = [
        "# V&V Plan",
        "",
        "| Requirement | Type | Case | Method | Condition | Stimulus | Acceptance criteria | Status | Missing |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in vv_plan.get("rows", ()):
        missing = ", ".join(str(item) for item in row.get("missing", ())) or "—"
        lines.append(
            "| {requirement} | {case_type} | {case} | {method} | {condition} | {stimulus} | {criteria} | {status} | {missing} |".format(
                requirement=_cell(row.get("requirement_id")),
                case_type=_cell(row.get("case_type_label") or row.get("case_type")),
                case=_cell(row.get("case_id") or "—"),
                method=_cell(row.get("method") or "—"),
                condition=_cell(row.get("test_condition") or "—"),
                stimulus=_cell(row.get("stimulus") or "—"),
                criteria=_cell(row.get("pass_criteria") or "—"),
                status=_cell(row.get("status") or "UNKNOWN"),
                missing=_cell(missing),
            )
        )
    return "\n".join(lines) + "\n"


def _architecture_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# Architecture Report",
        "",
        f"Status: **{report.get('status', 'UNKNOWN')}**",
        "",
        "## Entity counts",
        "",
        "| Kind | Count |",
        "| --- | ---: |",
    ]
    for kind, count in sorted(dict(report.get("entity_counts", {})).items()):
        lines.append(f"| {_cell(kind)} | {int(count)} |")
    lines.extend([
        "",
        "## Trace and allocation summary",
        "",
        f"- Valid trace edges: {int(report.get('valid_trace_edge_count', 0))}",
        f"- Invalid trace edges: {int(report.get('invalid_trace_edge_count', 0))}",
        f"- Allocations: {int(report.get('allocation_count', 0))}",
        "",
        "## Architecture decision evidence",
        "",
        "### Logical alternatives",
        "",
        "| Alternative | Score | Timing cuts | Safety pairs | Safety violations |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    synthesis = report.get("architecture_synthesis", {})
    logical = synthesis.get("logical", {}) if isinstance(synthesis, Mapping) else {}
    candidates = logical.get("candidates", ()) if isinstance(logical, Mapping) else ()
    if candidates:
        for candidate in candidates:
            lines.append(
                "| {alternative} | {score} | {timing} | {safety} | {violations} |".format(
                    alternative=_cell(candidate.get("alternative", "")),
                    score=_cell(candidate.get("score", "")),
                    timing=_cell(candidate.get("timing_cut_count", 0)),
                    safety=_cell(candidate.get("safety_isolation_count", 0)),
                    violations=_cell(candidate.get("safety_violation_count", 0)),
                )
            )
    else:
        lines.append("| No logical alternatives | — | — | — | — |")
    decision_metrics = report.get("methodology_metrics", {})
    if isinstance(decision_metrics, Mapping) and decision_metrics.get("logical_safety_review_required"):
        lines.extend([
            "",
            "Safety isolation review required: the current logical partition violates an explicit safety separation constraint.",
        ])
    physical = synthesis.get("physical", {}) if isinstance(synthesis, Mapping) else {}
    rows = physical.get("rows", ()) if isinstance(physical, Mapping) else ()
    lines.extend([
        "",
        "### Physical feasibility",
        "",
        "| Physical | Status | Missing measurements | Conflicts |",
        "| --- | --- | --- | ---: |",
    ])
    if rows:
        for row in rows:
            lines.append(
                "| {physical} | {status} | {missing} | {conflicts} |".format(
                    physical=_cell(row.get("physical_id", "")),
                    status=_cell(row.get("status", "")),
                    missing=_cell(", ".join(str(item) for item in row.get("missing_fields", ())) or "—"),
                    conflicts=_cell(len(row.get("conflicts", ()))),
                )
            )
    else:
        lines.append("| No physical feasibility rows | — | — | — |")
    lines.extend([
        "",
        "## Gaps",
        "",
    ])
    gaps = list(report.get("gaps", ()))
    if not gaps:
        lines.append("No recorded RFLP gaps.")
    else:
        for gap in gaps:
            lines.append(
                f"- {_cell(gap.get('requirement_id', gap.get('id', 'gap')))}: "
                f"{_cell(', '.join(str(item) for item in gap.get('missing', ())) or 'review')}"
            )
    vv_gaps = list(report.get("vv_gaps", ()))
    if vv_gaps:
        lines.extend(["", "## V&V gaps", ""])
        for row in vv_gaps:
            lines.append(
                f"- {_cell(row.get('requirement_id', 'requirement'))}: "
                f"{_cell(row.get('case_type_label') or row.get('case_type') or 'V&V')} "
                f"({_cell(row.get('status', 'INCOMPLETE'))})"
            )
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


__all__ = ["DELIVERABLE_FORMAT", "EngineeringDeliverableService", "REQUIRED_MEMBERS"]
