"""Immutable contracts for natural-language CAD and design review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rflp_lite.domain.canonical import canonical_hash


Pair = tuple[str, Any]


@dataclass(frozen=True, slots=True)
class DesignIntent:
    id: str
    statement: str
    target_kind: str
    target_name: str
    parameters: tuple[Pair, ...] = ()
    material: str = ""
    connection_requirements: tuple[str, ...] = ()
    context_model_ids: tuple[str, ...] = ()
    source_requirement_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    provenance: str = "rule"
    structure_options: tuple[dict[str, str], ...] = ()

    @property
    def input_hash(self) -> str:
        return canonical_hash(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "target_kind": self.target_kind,
            "target_name": self.target_name,
            "parameters": dict(self.parameters),
            "material": self.material,
            "connection_requirements": list(self.connection_requirements),
            "context_model_ids": list(self.context_model_ids),
            "source_requirement_ids": list(self.source_requirement_ids),
            "confidence": self.confidence,
            "provenance": self.provenance,
            "structure_options": [dict(item) for item in self.structure_options],
            "input_hash": self.input_hash,
        }


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    id: str
    question: str
    ambiguity: str
    options: tuple[str, ...] = ()
    recommendation: str = ""
    rationale: str = ""
    severity: str = "high"
    status: str = "open"


@dataclass(frozen=True, slots=True)
class CadOperation:
    id: str
    operation: str
    parameters: tuple[Pair, ...] = ()
    depends_on: tuple[str, ...] = ()
    expected_result: str = ""
    reversible: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation": self.operation,
            "parameters": dict(self.parameters),
            "depends_on": list(self.depends_on),
            "expected_result": self.expected_result,
            "reversible": self.reversible,
        }


@dataclass(frozen=True, slots=True)
class CadExecutionPlan:
    id: str
    intent_id: str
    operations: tuple[CadOperation, ...]
    risks: tuple[str, ...] = ()
    status: str = "draft"
    approval_status: str = "pending"
    preview_hash: str = ""
    model_context_ids: tuple[str, ...] = ()
    source_requirement_ids: tuple[str, ...] = ()
    selected_structure_option_id: str = ""

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "intent_id": self.intent_id,
            "operations": [item.as_dict() for item in self.operations],
            "risks": list(self.risks),
            "status": self.status,
            "approval_status": self.approval_status,
            "preview_hash": self.preview_hash,
            "model_context_ids": list(self.model_context_ids),
            "source_requirement_ids": list(self.source_requirement_ids),
            "selected_structure_option_id": self.selected_structure_option_id,
            "plan_hash": self.plan_hash,
        }


@dataclass(frozen=True, slots=True)
class CadModelReference:
    id: str
    cad_system: str
    adapter_version: str
    document_id: str
    revision: int
    units: str
    model_format: str
    artifact_hash: str
    status: str = "preview"
    source_kind: str = "development"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cad_system": self.cad_system,
            "adapter_version": self.adapter_version,
            "document_id": self.document_id,
            "revision": self.revision,
            "units": self.units,
            "model_format": self.model_format,
            "artifact_hash": self.artifact_hash,
            "status": self.status,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class DrawingAnnotation:
    id: str
    annotation_kind: str
    target_feature_id: str
    value: str
    part_id: str = ""
    unit: str = ""
    tolerance: str = ""
    datum: str = ""
    standard: str = ""
    view: str = "top"
    views: tuple[str, ...] = ("top", "isometric")
    position: tuple[float, float] = (0.0, 0.0)
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    rationale: str = ""
    status: str = "candidate"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "annotation_kind": self.annotation_kind,
            "target_feature_id": self.target_feature_id,
            "part_id": self.part_id,
            "value": self.value,
            "unit": self.unit,
            "tolerance": self.tolerance,
            "datum": self.datum,
            "standard": self.standard,
            "view": self.view,
            "views": list(self.views),
            "position": list(self.position),
            "bounds": list(self.bounds),
            "rationale": self.rationale,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class DesignFinding:
    id: str
    rule_id: str
    rule_version: str
    category: str
    severity: str
    part_id: str
    feature_id: str
    location: tuple[float, ...] = ()
    message: str = ""
    evidence: tuple[Pair, ...] = ()
    recommendation: str = ""
    status: str = "open"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "category": self.category,
            "severity": self.severity,
            "part_id": self.part_id,
            "feature_id": self.feature_id,
            "location": list(self.location),
            "message": self.message,
            "evidence": dict(self.evidence),
            "recommendation": self.recommendation,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class DesignReview:
    id: str
    model_id: str
    annotations: tuple[DrawingAnnotation, ...] = ()
    findings: tuple[DesignFinding, ...] = ()
    status: str = "needs_review"
    input_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "annotations": [item.as_dict() for item in self.annotations],
            "findings": [item.as_dict() for item in self.findings],
            "status": self.status,
            "input_hash": self.input_hash,
        }


__all__ = [
    "CadExecutionPlan",
    "CadModelReference",
    "CadOperation",
    "ClarificationQuestion",
    "DesignFinding",
    "DesignIntent",
    "DesignReview",
    "DrawingAnnotation",
]
