"""Configuration contract for the optional project-analysis domain guidance."""

from __future__ import annotations

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


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

DEFAULT_ANALYSIS_CONFIG: dict[str, object] = {
    "enabled": False,
    "domain_pack_id": None,
    "domain_pack_version": None,
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
    return tuple(_clone(item) for item in COMMON_ANALYSIS_PACKS)


def normalize_analysis_config(value: object) -> dict[str, object]:
    """Normalize the project-level optional pack setting.

    A missing value and a disabled value are intentionally equivalent.  This
    keeps older workbenches domain-neutral after schema migration and prevents
    a packaged narrow-domain example from being selected implicitly.
    """

    if value is None:
        return _clone(DEFAULT_ANALYSIS_CONFIG)
    if not isinstance(value, dict):
        raise ContractViolation("分析配置必须是对象")

    enabled = bool(value.get("enabled", value.get("domain_pack_enabled", False)))
    if not enabled:
        return _clone(DEFAULT_ANALYSIS_CONFIG)

    pack_id = str(value.get("domain_pack_id", "")).strip()
    if not pack_id:
        raise ContractViolation("启用专业领域包时必须提供 domain_pack_id")
    pack = _pack(pack_id)
    if pack is None:
        raise ContractViolation(
            f"项目分析只允许配置常见领域包: {', '.join(item['id'] for item in COMMON_ANALYSIS_PACKS)}"
        )

    raw_version = value.get("domain_pack_version", pack["version"])
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise ContractViolation("domain_pack_version 必须是正整数") from exc
    if version != int(pack["version"]):
        raise ContractViolation(f"领域包 {pack_id} 只支持版本 {pack['version']}")

    return {
        "enabled": True,
        "domain_pack_id": pack_id,
        "domain_pack_version": version,
        "provenance": {
            "source": str((value.get("provenance") or {}).get("source", "explicit"))
            if isinstance(value.get("provenance"), dict)
            else "explicit",
            "reason": "user-selected-common-domain-pack",
        },
    }


def analysis_config_changed(previous: object, current: object) -> bool:
    return normalize_analysis_config(previous) != normalize_analysis_config(current)
