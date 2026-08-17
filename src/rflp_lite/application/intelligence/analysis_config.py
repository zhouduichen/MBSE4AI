"""Configuration contract for the optional project-analysis domain guidance."""

from __future__ import annotations

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.application.intelligence.pack_composition import (
    DEFAULT_BASE_PACK_ID,
    available_analysis_pack_ids,
    normalize_pack_selection,
)


# Only broad, reusable guidance packs belong on the normal project-analysis
# path.  Narrow packs remain available to their explicit legacy/discovery
# workflows and cannot become an accidental default for a new project.
COMMON_ANALYSIS_PACKS: tuple[dict[str, object], ...] = (
    {
        "id": "common-v1",
        "version": 1,
        "label": "通用 MBSE 发现框架",
        "description": "跨行业的利益相关方、场景、需求、功能和架构分析提示。",
    },
)

_ANALYSIS_PACK_LABELS = {
    "common-v1": ("通用 MBSE 发现框架", "跨行业的利益相关方、场景、需求、功能和架构分析提示。"),
    "medical-v1": ("医疗行业系统工程", "面向医疗服务、患者安全、临床流程和数据治理的通用指导。"),
    "aviation-v1": ("航空与空域系统", "面向飞行任务、适航、空域运行和持续安全的通用指导。"),
    "automotive-v1": ("汽车与智能移动系统", "面向车辆、道路、乘员、服务和生命周期的通用指导。"),
    "industrial-v1": ("工业装备与生产系统", "面向工业设备、工艺、产线、运维和工厂环境的通用指导。"),
    "energy-infrastructure-v1": ("能源与基础设施", "面向能源供给、基础设施网络、容量和韧性的通用指导。"),
    "software-data-v1": ("软件与数据系统", "面向软件服务、数据生命周期、平台和信息安全的通用指导。"),
    "mechanical-v1": ("机械工程学科", "面向结构、运动、载荷、制造和维护的工程关注点。"),
    "electrical-v1": ("电气工程学科", "面向供配电、信号、接口、电磁兼容和故障保护的工程关注点。"),
    "software-v1": ("软件工程学科", "面向软件架构、接口、质量、部署和演化的工程关注点。"),
    "control-v1": ("控制与自动化学科", "面向感知、决策、执行、稳定性和降级控制的工程关注点。"),
    "thermal-v1": ("热与环境工程学科", "面向热源、传热、环境边界和热安全的工程关注点。"),
    "safety-v1": ("安全与风险工程学科", "面向危害、风险、屏障、验证证据和事故学习的工程关注点。"),
    "manufacturing-v1": ("制造与质量工程学科", "面向工艺能力、装配、检验、供应链和质量追溯的工程关注点。"),
    "urban-medical-aam-v1": ("城市医疗空中交通组合", "由医疗、航空、机械、电气、控制和安全指导组合而成的场景覆盖层。"),
}

DEFAULT_ANALYSIS_CONFIG: dict[str, object] = {
    "enabled": False,
    "domain_pack_id": None,
    "domain_pack_version": None,
    "base_pack_id": DEFAULT_BASE_PACK_ID,
    "industry_pack_ids": [],
    "discipline_pack_ids": [],
    "overlay_pack_ids": [],
    "provenance": {"source": "default", "reason": "domain-neutral-analysis"},
}


def _clone(value: object) -> object:
    import json

    return json.loads(canonical_json(value))


def _pack(pack_id: str) -> dict[str, object] | None:
    return next(
        (item for item in COMMON_ANALYSIS_PACKS if item["id"] == pack_id),
        None,
    )


def available_analysis_domain_packs() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": pack_id,
            "version": 1,
            "label": _ANALYSIS_PACK_LABELS.get(pack_id, (pack_id, ""))[0],
            "description": _ANALYSIS_PACK_LABELS.get(pack_id, (pack_id, ""))[1],
        }
        for pack_id in available_analysis_pack_ids()
    )


def normalize_analysis_config(value: object) -> dict[str, object]:
    """Normalize the project-level optional pack setting.

    A missing value and a disabled value are intentionally equivalent.  This
    keeps older workbenches domain-neutral after schema migration and prevents
    a packaged narrow-domain example from being selected implicitly.
    """

    normalized = normalize_pack_selection(value)
    if value is None or not isinstance(value, dict):
        return _clone(DEFAULT_ANALYSIS_CONFIG)

    raw_version = value.get("domain_pack_version")
    if raw_version not in (None, ""):
        try:
            version = int(raw_version)
        except (TypeError, ValueError) as exc:
            raise ContractViolation("domain_pack_version 必须是正整数") from exc
        if version < 1:
            raise ContractViolation("domain_pack_version 必须是正整数")
        normalized["domain_pack_version"] = version

    normalized["provenance"] = {
        "source": str(normalized["provenance"].get("source", "explicit"))
        if isinstance(normalized.get("provenance"), dict)
        else "explicit",
        "reason": str(normalized["provenance"].get("reason", "layered-domain-pack"))
        if isinstance(normalized.get("provenance"), dict)
        else "layered-domain-pack",
    }
    if normalized["enabled"] and normalized.get("domain_pack_id") is None:
        normalized["domain_pack_id"] = (
            normalized["overlay_pack_ids"][0]
            if normalized["overlay_pack_ids"]
            else normalized["base_pack_id"]
        )
    return normalized


def analysis_config_changed(previous: object, current: object) -> bool:
    return normalize_analysis_config(previous) != normalize_analysis_config(current)
