"""Vendor-neutral CAD, drawing and design-rule ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from rflp_lite.domain.detail_design import (
    CadExecutionPlan,
    CadModelReference,
    DesignFinding,
    DrawingAnnotation,
)


@dataclass(frozen=True, slots=True)
class CadCapabilities:
    cad_system: str
    adapter_version: str
    supported_operations: tuple[str, ...]
    units: tuple[str, ...] = ("mm",)
    source_kind: str = "development"
    writable: bool = False
    license_status: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "cad_system": self.cad_system,
            "adapter_version": self.adapter_version,
            "supported_operations": list(self.supported_operations),
            "units": list(self.units),
            "source_kind": self.source_kind,
            "writable": self.writable,
            "license_status": self.license_status,
        }


@dataclass(frozen=True, slots=True)
class CadOperationResult:
    model: CadModelReference
    model_payload: Mapping[str, object] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnnotationResult:
    annotations: tuple[DrawingAnnotation, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuleReviewResult:
    findings: tuple[DesignFinding, ...]
    diagnostics: tuple[str, ...] = ()


class CadPort(Protocol):
    def capabilities(self) -> CadCapabilities: ...

    def preview_plan(
        self, plan: CadExecutionPlan, context: Mapping[str, object] | None = None
    ) -> CadOperationResult: ...

    def execute_plan(
        self, plan: CadExecutionPlan, context: Mapping[str, object] | None = None
    ) -> CadOperationResult: ...


class DrawingPort(Protocol):
    def generate_annotations(
        self, model: Mapping[str, object], context: Mapping[str, object] | None = None
    ) -> AnnotationResult: ...


class DesignRulePort(Protocol):
    def review(
        self, model: Mapping[str, object], context: Mapping[str, object] | None = None
    ) -> RuleReviewResult: ...


__all__ = [
    "AnnotationResult",
    "CadCapabilities",
    "CadOperationResult",
    "CadPort",
    "DesignRulePort",
    "DrawingPort",
    "RuleReviewResult",
]
