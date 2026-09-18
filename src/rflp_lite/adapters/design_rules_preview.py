"""Deterministic development DFM/DFA review adapter."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from html import escape

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.detail_design import DesignFinding
from rflp_lite.ports.cad import RuleReviewResult


_VERSION = "dfm-dfa-preview-1.0"
_DEFAULT_RULE_SET = "generic_preview"
_RULE_PROFILES = {
    "generic_preview": {
        "wall_min_mm": 1.5,
        "fillet_min_mm": 0.5,
        "hole_edge_ratio": 1.5,
    },
    "cnc_machined": {
        "wall_min_mm": 2.0,
        "fillet_min_mm": 1.0,
        "hole_edge_ratio": 2.0,
    },
    "additive_preview": {
        "wall_min_mm": 1.0,
        "fillet_min_mm": 0.3,
        "hole_edge_ratio": 1.2,
    },
}


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


def _review_context(model: Mapping[str, object], context: Mapping[str, object] | None):
    merged: MutableMapping[str, object] = {}
    model_context = model.get("design_review_context")
    if isinstance(model_context, Mapping):
        merged.update(model_context)
    if isinstance(context, Mapping):
        merged.update(context)
    requested = str(merged.get("rule_set", _DEFAULT_RULE_SET)).strip() or _DEFAULT_RULE_SET
    profile = _RULE_PROFILES.get(requested)
    return requested, profile or _RULE_PROFILES[_DEFAULT_RULE_SET], profile is None, merged


def _assembly_findings(
    model: Mapping[str, object], context: Mapping[str, object], rule_set: str
) -> list[DesignFinding]:
    raw = context.get("assembly_interfaces")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        return [_finding(
            "dfa.assembly_interface", "dfa", "high", "assembly", "assembly",
            "装配接口声明不是列表，无法完成装配可达性检查。",
            {"assembly_interfaces": raw, "rule_set": rule_set},
            "将装配接口声明为包含 part_id、feature_id 和 interface 的列表。",
        )]
    parts = {
        str(part.get("id", "")): part
        for part in model.get("parts", ())
        if isinstance(part, Mapping) and str(part.get("id", ""))
    }
    findings: list[DesignFinding] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            findings.append(_finding(
                "dfa.assembly_interface", "dfa", "high", "assembly", f"interface-{index}",
                "装配接口记录格式无效。", {"interface_record": item, "rule_set": rule_set},
                "补充 part_id、feature_id、interface 和 required 字段。",
            ))
            continue
        if item.get("required", True) is False:
            continue
        part_id = str(item.get("part_id", "")).strip()
        feature_id = str(item.get("feature_id", "")).strip()
        interface = str(item.get("interface", "")).strip()
        part = parts.get(part_id)
        features = part.get("features", ()) if isinstance(part, Mapping) else ()
        feature_ids = {
            str(feature.get("id", ""))
            for feature in features
            if isinstance(feature, Mapping)
        }
        missing = not part_id or not feature_id or not interface or part is None or feature_id not in feature_ids
        if not missing:
            continue
        bbox = part.get("bbox_mm", ()) if isinstance(part, Mapping) else ()
        location = tuple(float(value) for value in bbox) if isinstance(bbox, (list, tuple)) else ()
        findings.append(_finding(
            "dfa.assembly_interface", "dfa", "high", part_id or "assembly", feature_id or f"interface-{index}",
            "必需装配接口在当前模型中缺失或未定义。",
            {
                "part_id": part_id,
                "feature_id": feature_id,
                "interface": interface,
                "required": True,
                "rule_set": rule_set,
            },
            "补充对应安装/定位/连接特征，并重新执行装配审查。",
            location,
        ))
    return findings


def _with_rule_context(finding: DesignFinding, rule_set: str, profile_name: str) -> DesignFinding:
    evidence = {"rule_set": rule_set, "rule_profile": profile_name}
    evidence.update(dict(finding.evidence))
    evidence_items = tuple((str(key), value) for key, value in evidence.items())
    return replace(
        finding,
        id=f"finding-{canonical_hash((finding.rule_id, finding.part_id, finding.feature_id, evidence_items))[:16]}",
        evidence=evidence_items,
    )


def _finding_summary(findings: tuple[DesignFinding, ...]) -> Mapping[str, object]:
    return {
        "total": len(findings),
        "by_severity": dict(sorted(Counter(item.severity for item in findings).items())),
        "by_category": dict(sorted(Counter(item.category for item in findings).items())),
    }


def _highlight_svg(model: Mapping[str, object], findings: tuple[DesignFinding, ...]) -> str:
    rows: list[str] = []
    y = 28.0
    parts = model.get("parts", ())
    for part in parts if isinstance(parts, (list, tuple)) else ():
        if not isinstance(part, Mapping):
            continue
        part_id = str(part.get("id", "part"))
        bbox = part.get("bbox_mm", ())
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 3:
            continue
        width = max(80.0, min(float(bbox[0]), 520.0))
        height = max(40.0, min(float(bbox[1]), 240.0))
        count = sum(item.part_id == part_id and item.severity in {"high", "critical"} for item in findings)
        color = "#d64545" if count else "#4b8bca"
        rows.append(f'<rect x="36" y="{y:g}" width="{width:g}" height="{height:g}" fill="none" stroke="{color}" stroke-width="3"/>')
        rows.append(f'<text x="36" y="{y - 7:g}" font-size="12">{escape(part_id)}</text>')
        if count:
            rows.append(f'<text x="44" y="{y + 18:g}" fill="{color}" font-size="11">risk: {count}</text>')
        y += height + 38.0
    height = max(90.0, y + 10.0)
    return '<svg xmlns="http://www.w3.org/2000/svg" width="620" height="%g" viewBox="0 0 620 %g">%s</svg>' % (height, height, "".join(rows))


class PreviewDesignRuleAdapter:
    id = "design-rules.vendor-neutral.preview"
    version = _VERSION

    def review(self, model: Mapping[str, object], context: Mapping[str, object] | None = None) -> RuleReviewResult:
        findings: list[DesignFinding] = []
        rule_set, profile, unknown_rule_set, review_context = _review_context(model, context)
        if unknown_rule_set:
            findings.append(_finding(
                "ruleset.unknown", "ruleset", "high", "model", "model",
                f"未识别的设计规则集：{rule_set}。当前仅能提供开发期参考检查。",
                {"requested_rule_set": rule_set},
                "选择已注册的 generic_preview、cnc_machined 或 additive_preview 规则集。",
            ))
        findings.extend(_assembly_findings(model, review_context, rule_set))
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
                if isinstance(wall, (int, float)) and float(wall) < float(profile["wall_min_mm"]):
                    findings.append(_finding(
                        "dfm.wall_thickness", "dfm", "high", part_id, feature_id,
                        f"壁厚低于当前规则集建议值 {profile['wall_min_mm']:g} mm。", {"wall_thickness_mm": wall, "minimum_mm": profile["wall_min_mm"]},
                        "增加壁厚或确认采用适用的薄壁工艺。", location,
                    ))
                radius = params.get("radius_mm")
                if isinstance(radius, (int, float)) and float(radius) < float(profile["fillet_min_mm"]):
                    findings.append(_finding(
                        "dfm.fillet_radius", "dfm", "medium", part_id, feature_id,
                        f"圆角半径低于当前规则集建议值 {profile['fillet_min_mm']:g} mm。", {"radius_mm": radius, "minimum_mm": profile["fillet_min_mm"]},
                        "增加圆角半径并检查相邻壁厚。", location,
                    ))
                diameter = params.get("diameter_mm")
                edge_distance = params.get("edge_distance_mm")
                if isinstance(diameter, (int, float)) and isinstance(edge_distance, (int, float)) and float(edge_distance) < float(profile["hole_edge_ratio"]) * float(diameter):
                    findings.append(_finding(
                        "dfm.hole_edge_distance", "dfm", "high", part_id, feature_id,
                        f"孔边距低于当前规则集要求的 {profile['hole_edge_ratio']:g} 倍孔径。", {"diameter_mm": diameter, "edge_distance_mm": edge_distance, "minimum_ratio": profile["hole_edge_ratio"]},
                        "增大孔边距或重新评估局部加强与工艺。", location,
                    ))
                if params.get("tool_access") is False:
                    findings.append(_finding(
                        "dfa.tool_access", "dfa", "high", part_id, feature_id,
                        "检测到刀具/装配工具不可达。", {"tool_access": False},
                        "调整特征方向、装配顺序或增加工具访问空间。", location,
                    ))
                if feature.get("kind") == "create_gear":
                    bore = params.get("bore_diameter_mm")
                    if not isinstance(bore, (int, float)) or float(bore) <= 0:
                        findings.append(_finding(
                            "dfm.gear_bore", "dfm", "high", part_id, feature_id,
                            "齿轮缺少有效中心孔参数，轴系装配接口尚未定义。",
                            {"bore_diameter_mm": bore}, "补充中心孔和轴系配合，并重新评审。", location,
                        ))
                if feature.get("kind") == "add_shaft_step":
                    step = params.get("diameter_mm")
                    base = params.get("base_diameter_mm")
                    if isinstance(step, (int, float)) and isinstance(base, (int, float)) and float(step) >= float(base):
                        findings.append(_finding(
                            "dfm.shaft_step", "dfm", "high", part_id, feature_id,
                            "阶梯轴段直径不小于基体直径，无法形成有效轴肩。",
                            {"diameter_mm": step, "base_diameter_mm": base}, "重新定义阶梯直径并确认轴肩过渡。", location,
                        ))
        profile_name = rule_set if not unknown_rule_set else _DEFAULT_RULE_SET
        final = tuple(_with_rule_context(item, rule_set, profile_name) for item in findings)
        summary = _finding_summary(final)
        evidence_hash = canonical_hash([item.as_dict() for item in final])
        return RuleReviewResult(
            final,
            (),
            {
                "risk_highlight_svg": _highlight_svg(model, final),
                "source_kind": "development",
                "rule_set": rule_set,
                "rule_version": _VERSION,
                "finding_summary": summary,
                "evidence_hash": evidence_hash,
            },
        )


__all__ = ["PreviewDesignRuleAdapter"]
