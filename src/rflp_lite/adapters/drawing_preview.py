"""Deterministic drawing/3D annotation preview adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.detail_design import DrawingAnnotation
from rflp_lite.ports.cad import AnnotationResult


_STANDARD = "GB/T 1804-m"
_GDT_STANDARD = "ASME Y14.5"


def _rects_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return lx < rx + rw and rx < lx + lw and ly < ry + rh and ry < ly + lh


def _place(
    used: list[tuple[float, float, float, float]],
    x: float,
    y: float,
    width: float = 28.0,
    height: float = 8.0,
) -> tuple[tuple[float, float], tuple[float, float, float, float], bool]:
    candidates = (
        (x, y), (x, y + 12), (x + 32, y), (x - 32, y),
        (x + 32, y + 12), (x - 32, y + 12), (x, y - 12),
    )
    for candidate_x, candidate_y in candidates:
        bounds = (candidate_x, candidate_y, width, height)
        if all(not _rects_overlap(bounds, item) for item in used):
            used.append(bounds)
            return (candidate_x, candidate_y), bounds, True
    bounds = (x, y, width, height)
    used.append(bounds)
    return (x, y), bounds, False


def _annotation(
    part_id: str,
    feature_id: str,
    kind: str,
    value: str,
    *,
    unit: str = "mm",
    tolerance: str = "",
    datum: str = "",
    standard: str = _STANDARD,
    anchor: tuple[float, float] = (0.0, 0.0),
    used: list[tuple[float, float, float, float]],
    rationale: str,
) -> DrawingAnnotation:
    position, bounds, placed = _place(used, *anchor)
    return DrawingAnnotation(
        id=f"annotation-{canonical_hash((part_id, feature_id, kind, value))[:16]}",
        annotation_kind=kind,
        target_feature_id=feature_id,
        value=value,
        unit=unit,
        tolerance=tolerance,
        datum=datum,
        standard=standard,
        view="top",
        views=("top", "isometric"),
        position=position,
        bounds=bounds,
        rationale=rationale,
        status="candidate" if placed else "needs_review",
    )


class PreviewDrawingAdapter:
    id = "drawing.vendor-neutral.preview"
    version = "drawing-preview-v1"

    def generate_annotations(
        self, model: Mapping[str, object], context: Mapping[str, object] | None = None
    ) -> AnnotationResult:
        annotations: list[DrawingAnnotation] = []
        diagnostics: list[str] = []
        used: list[tuple[float, float, float, float]] = []
        parts = model.get("parts", ())
        for part in parts if isinstance(parts, (list, tuple)) else ():
            if not isinstance(part, Mapping):
                continue
            part_id = str(part.get("id", "part"))
            bbox = part.get("bbox_mm", ())
            dimensions = tuple(float(value) for value in bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 3 else ()
            if len(dimensions) == 3 and all(value > 0 for value in dimensions):
                for name, value, anchor in (
                    ("length", dimensions[0], (0.0, -14.0)),
                    ("width", dimensions[1], (dimensions[0] / 2, dimensions[1] + 14.0)),
                    ("height", dimensions[2], (dimensions[0] + 36.0, dimensions[1] / 2)),
                ):
                    annotations.append(_annotation(
                        part_id, f"{part_id}:{name}", "dimension", f"{value:g}",
                        anchor=anchor, used=used,
                        rationale="由参数化实体包络自动生成，2D/3D 共享该语义标注。",
                    ))
            else:
                diagnostics.append(f"part {part_id} has no complete bounding box")
            annotations.append(_annotation(
                part_id, f"{part_id}:base", "datum", "A", unit="", datum="A",
                standard=_GDT_STANDARD, anchor=(0.0, 0.0), used=used,
                rationale="将基准面作为装配与几何公差的基准。",
            ))
            annotations.append(_annotation(
                part_id, f"{part_id}:flatness", "feature_control_frame", "平面度 0.20 | A",
                unit="mm", datum="A", standard=_GDT_STANDARD, anchor=(0.0, 28.0), used=used,
                rationale="开发期 GD&T 建议；正式出图仍需真实 CAD/制图工具复核。",
            ))
            features = part.get("features", ())
            for feature in features if isinstance(features, (list, tuple)) else ():
                if not isinstance(feature, Mapping):
                    continue
                parameters = feature.get("parameters")
                if not isinstance(parameters, Mapping) or "diameter_mm" not in parameters:
                    continue
                annotations.append(_annotation(
                    part_id,
                    str(feature.get("id", "hole")),
                    "hole_diameter",
                    f"⌀{float(parameters['diameter_mm']):g}",
                    tolerance="±0.10",
                    anchor=(dimensions[0] / 2 if dimensions else 0.0, dimensions[1] / 2 if len(dimensions) > 1 else 0.0),
                    used=used,
                    rationale="孔径与一般尺寸公差建议。",
                ))
        if any(item.status == "needs_review" for item in annotations):
            diagnostics.append("annotation placement collision requires review")
        return AnnotationResult(tuple(annotations), tuple(diagnostics))


__all__ = ["PreviewDrawingAdapter"]
