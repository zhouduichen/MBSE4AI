"""Deterministic development DFM/DFA review adapter."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.detail_design import DesignFinding
from rflp_lite.ports.cad import RuleReviewResult


_VERSION = "dfm-dfa-preview-1.0"


def _finding(
    rule_id: str,
    category: str,
    severity: str,
    part_id: str,
    feature_id: str,
    message: str,
    evidence: Mapping[str, object],
    recommendation: str,
    location: tuple[float, ...] = (),
) -> DesignFinding:
    return DesignFinding(
        id=f"finding-{canonical_hash((rule_id, part_id, feature_id, evidence))[:16]}",
        rule_id=rule_id,
        rule_version=_VERSION,
        category=category,
        severity=severity,
        part_id=part_id,
        feature_id=feature_id,
        location=location,
        message=message,
        evidence=tuple((str(key), value) for key, value in evidence.items()),
        recommendation=recommendation,
    )


class PreviewDesignRuleAdapter:
    id = "design-rules.vendor-neutral.preview"
    version = _VERSION

    def review(self, model: Mapping[str, object], context: Mapping[str, object] | None = None) -> RuleReviewResult:
        findings: list[DesignFinding] = []
        parts = model.get("parts", ())
        for part in parts if isinstance(parts, (list, tuple)) else ():
            if not isinstance(part, Mapping):
                continue
            part_id = str(part.get("id", "part"))
            bbox = part.get("bbox_mm", ())
            location = tuple(float(value) for value in bbox) if isinstance(bbox, (list, tuple)) else ()
            material = str(part.get("material", "")).strip()
            if not material:
                findings.append(_finding(
                    "material.required", "material", "medium", part_id, part_id,
                    "未指定材料，无法完成强度、质量和制造性评估。",
                    {"material": material}, "补充材料并确认材料牌号。", location,
                ))
            if len(location) != 3 or any(value <= 0 for value in location):
                findings.append(_finding(
                    "geometry.envelope", "geometry", "high", part_id, part_id,
                    "零件缺少完整正包络尺寸。", {"bbox_mm": location},
                    "补充长、宽、高/厚度后重新生成。", location,
                ))
            features = part.get("features", ())
            for feature in features if isinstance(features, (list, tuple)) else ():
                if not isinstance(feature, Mapping):
                    continue
                feature_id = str(feature.get("id", "feature"))
                params = feature.get("parameters")
                if not isinstance(params, Mapping):
                    continue
                wall = params.get("wall_thickness_mm")
                if isinstance(wall, (int, float)) and float(wall) < 1.5:
                    findings.append(_finding(
                        "dfm.wall_thickness", "dfm", "high", part_id, feature_id,
                        "壁厚低于开发期最小制造建议值 1.5 mm。", {"wall_thickness_mm": wall, "minimum_mm": 1.5},
                        "增加壁厚或确认采用适用的薄壁工艺。", location,
                    ))
                radius = params.get("radius_mm")
                if isinstance(radius, (int, float)) and float(radius) < 0.5:
                    findings.append(_finding(
                        "dfm.fillet_radius", "dfm", "medium", part_id, feature_id,
                        "圆角半径低于开发期刀具/应力集中建议值 0.5 mm。", {"radius_mm": radius, "minimum_mm": 0.5},
                        "增加圆角半径并检查相邻壁厚。", location,
                    ))
                diameter = params.get("diameter_mm")
                edge_distance = params.get("edge_distance_mm")
                if isinstance(diameter, (int, float)) and isinstance(edge_distance, (int, float)) and float(edge_distance) < 1.5 * float(diameter):
                    findings.append(_finding(
                        "dfm.hole_edge_distance", "dfm", "high", part_id, feature_id,
                        "孔边距低于孔径 1.5 倍的开发期建议值。", {"diameter_mm": diameter, "edge_distance_mm": edge_distance},
                        "增大孔边距或重新评估局部加强与工艺。", location,
                    ))
                if params.get("tool_access") is False:
                    findings.append(_finding(
                        "dfa.tool_access", "dfa", "high", part_id, feature_id,
                        "检测到刀具/装配工具不可达。", {"tool_access": False},
                        "调整特征方向、装配顺序或增加工具访问空间。", location,
                    ))
        return RuleReviewResult(tuple(findings), ())


__all__ = ["PreviewDesignRuleAdapter"]
