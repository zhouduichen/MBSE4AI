"""Review evidence derived from a real FreeCAD geometry payload."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from rflp_lite.adapters.design_rules_preview import PreviewDesignRuleAdapter
from rflp_lite.adapters.drawing_preview import PreviewDrawingAdapter
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.detail_design import DesignFinding
from rflp_lite.ports.cad import AnnotationResult, RuleReviewResult


_RULE_VERSION = "dfm-dfa-freecad-1.0"


def _shape_finding(
    rule_id: str,
    part_id: str,
    message: str,
    evidence: Mapping[str, Any],
    recommendation: str,
    location: tuple[float, ...],
) -> DesignFinding:
    return DesignFinding(
        id=f"finding-{canonical_hash((rule_id, part_id, evidence))[:16]}",
        rule_id=rule_id,
        rule_version=_RULE_VERSION,
        category="geometry",
        severity="high",
        part_id=part_id,
        feature_id=part_id,
        location=location,
        message=message,
        evidence=tuple((str(key), value) for key, value in evidence.items()),
        recommendation=recommendation,
    )


def _risk_svg(
    model: Mapping[str, object],
    findings: tuple[DesignFinding, ...],
    annotations: tuple[object, ...] = (),
) -> str:
    parts = model.get("parts", ())
    rows: list[str] = []
    y = 30.0
    for part in parts if isinstance(parts, (list, tuple)) else ():
        if not isinstance(part, Mapping):
            continue
        part_id = str(part.get("id", "part"))
        bbox = part.get("bbox_mm", ())
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 3:
            continue
        width = max(80.0, min(float(bbox[0]), 520.0))
        height = max(40.0, min(float(bbox[1]), 260.0))
        part_findings = tuple(item for item in findings if item.part_id == part_id and item.severity in {"high", "critical"})
        color = "#d64545" if part_findings else "#4b8bca"
        rows.append(f'<rect x="40" y="{y:g}" width="{width:g}" height="{height:g}" fill="none" stroke="{color}" stroke-width="3"/>')
        rows.append(f'<text x="40" y="{y - 8:g}" font-size="12">{escape(part_id)}</text>')
        if part_findings:
            rows.append(f'<text x="48" y="{y + 20:g}" fill="{color}" font-size="11">risk: {len(part_findings)}</text>')
        y += height + 45.0
    for index, annotation in enumerate(annotations):
        value = getattr(annotation, "value", "")
        unit = getattr(annotation, "unit", "")
        rows.append(f'<text x="40" y="{y + index * 16:g}" font-size="11">{escape(str(value))} {escape(str(unit))}</text>')
    canvas_height = max(100.0, y + 10.0)
    return '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="%g" viewBox="0 0 640 %g">%s</svg>' % (canvas_height, canvas_height, "".join(rows))


class FreeCadDrawingAdapter(PreviewDrawingAdapter):
    id = "drawing.freecad.geometry"
    version = "freecad-geometry-pmi-v1"

    def generate_annotations(
        self, model: Mapping[str, object], context: Mapping[str, object] | None = None
    ) -> AnnotationResult:
        result = super().generate_annotations(model, context)
        drawing_svg = _risk_svg(model, (), result.annotations)
        return AnnotationResult(
            result.annotations,
            result.diagnostics,
            {
                "drawing_backend": "FreeCAD geometry projection",
                "source_kind": "real",
                "drawing_svg": drawing_svg,
                "drawing_hash": canonical_hash(drawing_svg),
                "annotation_standard": "GB/T 1804-m + ASME Y14.5 candidate",
            },
        )


class FreeCadDesignRuleAdapter(PreviewDesignRuleAdapter):
    id = "design-rules.freecad.geometry"
    version = _RULE_VERSION

    def review(self, model: Mapping[str, object], context: Mapping[str, object] | None = None) -> RuleReviewResult:
        base = super().review(model, context)
        findings = list(base.findings)
        parts = model.get("parts", ())
        for part in parts if isinstance(parts, (list, tuple)) else ():
            if not isinstance(part, Mapping):
                continue
            part_id = str(part.get("id", "part"))
            raw_bbox = part.get("bbox_mm", ())
            location = tuple(float(item) for item in raw_bbox) if isinstance(raw_bbox, (list, tuple)) else ()
            if part.get("shape_valid") is False:
                findings.append(_shape_finding(
                    "geometry.invalid_solid", part_id,
                    "FreeCAD 实体拓扑无效。", {"shape_valid": False},
                    "修复实体拓扑后重新生成模型。", location,
                ))
            volume = part.get("volume_mm3")
            if isinstance(volume, (int, float)) and float(volume) <= 0:
                findings.append(_shape_finding(
                    "geometry.zero_volume", part_id,
                    "FreeCAD 实体体积为零，无法作为可制造实体。", {"volume_mm3": volume},
                    "检查特征顺序、布尔运算和实体闭合性。", location,
                ))
        final = tuple(findings)
        return RuleReviewResult(
            final,
            base.diagnostics,
            {
                "review_backend": "FreeCAD geometry",
                "source_kind": "real",
                "risk_highlight_svg": _risk_svg(model, final),
            },
        )


__all__ = ["FreeCadDesignRuleAdapter", "FreeCadDrawingAdapter"]
