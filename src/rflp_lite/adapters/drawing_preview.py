"""Deterministic drawing/3D annotation preview adapter."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
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


def _bbox(part: Mapping[str, object]) -> tuple[float, float, float] | None:
    raw = part.get("bbox_mm", ())
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    return values if all(value > 0 for value in values) else None


def _drawing_svg(
    model: Mapping[str, object], annotations: tuple[DrawingAnnotation, ...]
) -> str:
    """Render a deterministic vendor-neutral 2D preview from shared semantics."""

    rows = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" '
        'viewBox="0 0 760 0" data-unit="mm">',
        "<title>Parametric 2D drawing preview</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    parts = model.get("parts", ())
    y = 28.0
    rendered = False
    for part in parts if isinstance(parts, (list, tuple)) else ():
        if not isinstance(part, Mapping):
            continue
        part_id = str(part.get("id", "part"))
        dimensions = _bbox(part)
        if dimensions is None:
            continue
        rendered = True
        length, width, height = dimensions
        scale = min(1.8, 240.0 / max(length, 1.0), 130.0 / max(width, 1.0))
        top_width = max(36.0, length * scale)
        top_height = max(24.0, width * scale)
        side_height = max(18.0, height * scale)
        x = 56.0
        rows.extend(
            (
                f'<g data-part-id="{escape(part_id, quote=True)}">',
                f'<text x="{x:g}" y="{y:g}" font-size="13" font-weight="600">{escape(part_id)} · top</text>',
                f'<rect x="{x:g}" y="{y + 8:g}" width="{top_width:g}" height="{top_height:g}" fill="#eef5fb" stroke="#2f5f8f"/>',
                f'<text x="{x:g}" y="{y + top_height + 24:g}" font-size="11">L {length:g} mm · W {width:g} mm</text>',
                f'<text x="{x:g}" y="{y + top_height + 50:g}" font-size="13" font-weight="600">{escape(part_id)} · side</text>',
                f'<rect x="{x:g}" y="{y + top_height + 58:g}" width="{top_width:g}" height="{side_height:g}" fill="#f7f2e8" stroke="#8b6a2f"/>',
                f'<text x="{x:g}" y="{y + top_height + side_height + 74:g}" font-size="11">L {length:g} mm · H {height:g} mm</text>',
                "</g>",
            )
        )
        y += top_height + side_height + 112.0
    if not rendered:
        rows.append('<text x="24" y="32" font-size="13">No valid bounding box available</text>')
        y = 56.0
    rows.append('<g data-annotations="shared-semantics">')
    y += 8.0
    for annotation in annotations:
        detail = annotation.value
        if annotation.tolerance:
            detail += f" {annotation.tolerance}"
        if annotation.datum:
            detail += f" | datum {annotation.datum}"
        rows.append(
            f'<text x="56" y="{y:g}" font-size="11" data-annotation-id="{escape(annotation.id, quote=True)}">'
            f'{escape(annotation.annotation_kind)}: {escape(detail)} [{escape(annotation.standard)}]</text>'
        )
        y += 16.0
    rows.extend(("</g>", "</svg>"))
    svg = "".join(rows)
    canvas_height = max(y + 16.0, 100.0)
    return svg.replace('viewBox="0 0 760 0"', f'viewBox="0 0 760 {canvas_height:g}"').replace(
        'height="100%"', f'height="{canvas_height:g}"'
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
            dimensions = _bbox(part) or ()
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
                feature_id = str(feature.get("id", "feature"))
                parameters = feature.get("parameters")
                if not isinstance(parameters, Mapping):
                    continue
                anchor = (
                    dimensions[0] / 2 if dimensions else 0.0,
                    dimensions[1] / 2 if len(dimensions) > 1 else 0.0,
                )
                if "diameter_mm" in parameters:
                    annotations.append(_annotation(
                        part_id, feature_id, "hole_diameter", f"⌀{float(parameters['diameter_mm']):g}",
                        tolerance="±0.10", anchor=anchor, used=used,
                        rationale="孔径与一般尺寸公差建议。",
                    ))
                if feature.get("kind") == "create_shell" and "wall_thickness_mm" in parameters:
                    annotations.append(_annotation(
                        part_id, feature_id, "wall_thickness", f"{float(parameters['wall_thickness_mm']):g}",
                        tolerance="±0.10", anchor=anchor, used=used,
                        rationale="壳体壁厚是强度、质量和制造审查的关键尺寸。",
                    ))
                if feature.get("kind") == "add_shaft_step" and "diameter_mm" in parameters:
                    annotations.append(_annotation(
                        part_id, feature_id, "shaft_step_diameter", f"⌀{float(parameters['diameter_mm']):g}",
                        tolerance="±0.05", anchor=anchor, used=used,
                        rationale="阶梯轴段直径用于装配定位与配合审查。",
                    ))
                if feature.get("kind") == "create_gear":
                    if "bore_diameter_mm" in parameters and float(parameters["bore_diameter_mm"]) > 0:
                        annotations.append(_annotation(
                            part_id, feature_id, "gear_bore_diameter", f"⌀{float(parameters['bore_diameter_mm']):g}",
                            tolerance="±0.05", anchor=anchor, used=used,
                            rationale="齿轮中心孔用于轴系装配配合审查。",
                        ))
                    if "module" in parameters and "teeth" in parameters:
                        annotations.append(_annotation(
                            part_id, feature_id, "gear_profile", f"m{float(parameters['module']):g} z{int(float(parameters['teeth']))}",
                            unit="1", anchor=anchor, used=used,
                            rationale="齿轮模数与齿数作为齿形候选的共享语义参数。",
                        ))
        if any(item.status == "needs_review" for item in annotations):
            diagnostics.append("annotation placement collision requires review")
        annotation_values = tuple(annotations)
        drawing_svg = _drawing_svg(model, annotation_values)
        return AnnotationResult(
            annotation_values,
            tuple(diagnostics),
            {
                "drawing_backend": "vendor-neutral-parametric-preview",
                "drawing_format": "svg",
                "drawing_svg": drawing_svg,
                "drawing_hash": canonical_hash(drawing_svg),
                "annotation_standard": f"{_STANDARD} + {_GDT_STANDARD} candidate",
                "source_kind": "development",
            },
        )


__all__ = ["PreviewDrawingAdapter"]
