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
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


DELIVERABLE_FORMAT = "ai4mbse.engineering-deliverable.v1"
REQUIRED_MEMBERS = (
    "manifest.json",
    "model.json",
    "model.sysml",
    "requirements.json",
    "rflp.json",
    "traceability.json",
    "vv-plan.json",
    "vv-plan.md",
    "architecture-report.json",
    "architecture-report.md",
)
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class EngineeringDeliverableService:
    """Compose user-facing engineering outputs without creating new model state."""

    def __init__(self, model_service):
        self.model_service = model_service

    def build(self, project_id: str) -> Mapping[str, object]:
        graph = self.model_service.graph(project_id)
        issues = tuple(self.model_service.issues(project_id))
        requirements = dict(build_requirements_view(graph, issues))
        rflp = dict(build_rflp_view(graph, issues))
        traceability = dict(build_traceability_view(graph, issues))
        assurance = dict(build_assurance_view(graph, issues))
        vv_plan = _vv_plan(assurance)
        architecture_report = _architecture_report(graph, rflp, traceability, assurance)
        model = _model_content(graph)
        artifacts = {
            "model": _artifact("model-json-v1", model, graph),
            "sysml": _artifact("sysml-v2-subset", graph_to_sysml(graph), graph),
            "requirements": _artifact("requirements-view-v1", requirements, graph),
            "rflp": _artifact("rflp-view-v1", rflp, graph),
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
            "model.sysml": str(artifacts["sysml"]["content"]).encode("utf-8"),
            "requirements.json": _json_bytes(artifacts["requirements"]["content"]),
            "rflp.json": _json_bytes(artifacts["rflp"]["content"]),
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


def _artifact(format_id: str, content: object, graph: ModelGraph) -> dict[str, object]:
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
        "sysml": "model.sysml",
        "requirements": "requirements.json",
        "rflp": "rflp.json",
        "traceability": "traceability.json",
        "vv_plan": "vv-plan.json",
        "architecture_report": "architecture-report.json",
    }[name]


def _model_content(graph: ModelGraph) -> dict[str, object]:
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
    }


def _vv_plan(assurance: Mapping[str, object]) -> dict[str, object]:
    rows = []
    for raw in assurance.get("verification_validation", ()):
        row = dict(raw)
        missing: list[str] = []
        case_type = str(row.get("case_type", ""))
        case_id = row.get("case_id")
        if not case_id:
            missing.append(case_type)
        else:
            if not str(row.get("method", "")).strip():
                missing.append("method")
            if not str(row.get("pass_criteria", "")).strip():
                missing.append("pass_criteria")
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
    metrics = dict(gates[-1].get("coverage_summary", {})) if gates else {}
    return {"rows": rows, "gates": gates, "metrics": metrics}


def _architecture_report(
    graph: ModelGraph,
    rflp: Mapping[str, object],
    traceability: Mapping[str, object],
    assurance: Mapping[str, object],
) -> dict[str, object]:
    counts = {
        kind.value: sum(entity.kind is kind for entity in graph.entities)
        for kind in EntityKind
    }
    edges = list(rflp.get("edges", ()))
    valid_edges = sum(bool(edge.get("valid_for_trace")) for edge in edges)
    gates = list(assurance.get("gates", ()))
    gate_passed = bool(gates) and all(bool(gate.get("passed")) for gate in gates)
    has_blocking_issue = any(bool(gate.get("blocking_issues")) for gate in gates)
    status = "PASS" if gate_passed else "BLOCKED" if has_blocking_issue else "DEGRADED"
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
        "gaps": list(rflp.get("gaps", ())),
    }


def _json_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _vv_markdown(vv_plan: Mapping[str, object]) -> str:
    lines = [
        "# V&V Plan",
        "",
        "| Requirement | Type | Case | Method | Acceptance criteria | Status | Missing |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in vv_plan.get("rows", ()):
        missing = ", ".join(str(item) for item in row.get("missing", ())) or "—"
        lines.append(
            "| {requirement} | {case_type} | {case} | {method} | {criteria} | {status} | {missing} |".format(
                requirement=_cell(row.get("requirement_id")),
                case_type=_cell(row.get("case_type_label") or row.get("case_type")),
                case=_cell(row.get("case_id") or "—"),
                method=_cell(row.get("method") or "—"),
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
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


__all__ = ["DELIVERABLE_FORMAT", "EngineeringDeliverableService", "REQUIRED_MEMBERS"]
