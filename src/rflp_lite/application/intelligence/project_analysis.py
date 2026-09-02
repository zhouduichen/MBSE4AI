"""One-call, domain-neutral analysis for a single requirements workbench."""

from __future__ import annotations

import json
from collections.abc import Iterable

from rflp_lite.application.review_queue import sync_review_queue
from rflp_lite.application.intelligence.analysis_config import (
    normalize_analysis_config,
)
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse


PROJECT_ANALYSIS_LENS = "project_analysis"
PROJECT_ANALYSIS_PACK_MARKER = "llm-project-analysis"
SCENARIO_TYPES = frozenset({"normal", "boundary", "failure", "recovery", "misuse"})
_LIMITS = {
    "stakeholders": 12,
    "concerns": 24,
    "needs": 24,
    "requirements": 24,
    "scenarios": 16,
    "architecture_nodes": 48,
    "relations": 96,
}

_TEXT = {"type": "string"}
_NON_EMPTY_TEXT = {"type": "string", "minLength": 1}
_TEXT_LIST = {"type": "array", "items": _TEXT}


def _item_schema(required: tuple[str, ...], properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "required": list(required),
        "properties": properties,
        "additionalProperties": True,
    }


_STAKEHOLDER_SCHEMA = _item_schema(
    ("id", "name", "category", "goals", "interactions"),
    {
        "id": _NON_EMPTY_TEXT,
        "name": _NON_EMPTY_TEXT,
        "category": _NON_EMPTY_TEXT,
        "goals": _TEXT_LIST,
        "interactions": _TEXT_LIST,
    },
)
_CONCERN_SCHEMA = _item_schema(
    ("id", "name", "stakeholder_id"),
    {"id": _NON_EMPTY_TEXT, "name": _NON_EMPTY_TEXT, "stakeholder_id": _TEXT},
)
_NEED_SCHEMA = _item_schema(
    ("id", "name", "statement", "stakeholder_id", "concern_id"),
    {
        "id": _NON_EMPTY_TEXT,
        "name": _NON_EMPTY_TEXT,
        "statement": _NON_EMPTY_TEXT,
        "stakeholder_id": _TEXT,
        "concern_id": _TEXT,
    },
)
_REQUIREMENT_SCHEMA = _item_schema(
    ("id", "statement", "subject", "predicate", "verification_method"),
    {
        "id": _NON_EMPTY_TEXT,
        "statement": _NON_EMPTY_TEXT,
        "subject": _NON_EMPTY_TEXT,
        "predicate": _NON_EMPTY_TEXT,
        "verification_method": _NON_EMPTY_TEXT,
    },
)
_SCENARIO_SCHEMA = _item_schema(
    ("id", "title", "scenario_type", "actors", "steps", "expected_outcomes"),
    {
        "id": _NON_EMPTY_TEXT,
        "title": _NON_EMPTY_TEXT,
        "scenario_type": _NON_EMPTY_TEXT,
        "actors": _TEXT_LIST,
        "steps": _TEXT_LIST,
        "expected_outcomes": _TEXT_LIST,
    },
)
_ARCHITECTURE_ITEM_SCHEMA = _item_schema(
    ("id", "name", "description"),
    {"id": _NON_EMPTY_TEXT, "name": _NON_EMPTY_TEXT, "description": _TEXT},
)
_CONCEPT_PROPOSAL_SCHEMA = _item_schema(
    (),
    {
        "summary": _TEXT,
        "alternatives": _TEXT_LIST,
        "rationale": _TEXT_LIST,
        "assumptions": _TEXT_LIST,
        "parameter_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": _NON_EMPTY_TEXT,
                    "value": {},
                    "unit": _TEXT,
                    "minimum": {},
                    "maximum": {},
                    "reason": _TEXT,
                },
                "additionalProperties": True,
            },
        },
    },
)


_RESPONSE_SCHEMA = {
    "type": "object",
    "required": [
        "system",
        "stakeholders",
        "concerns",
        "needs",
        "requirements",
        "scenarios",
        "architecture",
        "open_questions",
    ],
    "properties": {
        "system": _item_schema(
            ("name", "domain", "mission"),
            {"name": _NON_EMPTY_TEXT, "domain": _NON_EMPTY_TEXT, "mission": _TEXT},
        ),
        "stakeholders": {"type": "array", "items": _STAKEHOLDER_SCHEMA},
        "concerns": {"type": "array", "items": _CONCERN_SCHEMA},
        "needs": {"type": "array", "items": _NEED_SCHEMA},
        "requirements": {"type": "array", "items": _REQUIREMENT_SCHEMA},
        "scenarios": {"type": "array", "items": _SCENARIO_SCHEMA},
        "architecture": _item_schema(
            ("functions", "logical_components", "physical_components", "interfaces", "relations"),
            {
                "functions": {"type": "array", "items": _ARCHITECTURE_ITEM_SCHEMA},
                "logical_components": {"type": "array", "items": _ARCHITECTURE_ITEM_SCHEMA},
                "physical_components": {"type": "array", "items": _ARCHITECTURE_ITEM_SCHEMA},
                "interfaces": {"type": "array", "items": _ARCHITECTURE_ITEM_SCHEMA},
                "relations": {"type": "array", "items": {"type": "object"}},
            },
        ),
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "diagnostics": {"type": "array", "items": {"type": "object"}},
        "concept_proposal": _CONCEPT_PROPOSAL_SCHEMA,
    },
}

_SYSTEM_PROMPT = """你是一个跨行业系统工程分析器，只返回符合 response_schema 的 JSON 对象。
只根据 input_regions 和当前项目上下文分析，不使用任何固定行业模板。先识别系统名称、领域和任务，
再生成利益相关方、关注点、利益相关方需要、可验证需求、正常/边界/故障/恢复/误操作五类场景，
以及 R/F/L/P 架构和接口。每个数组项都必须填写真实、简短、非空的 name 或 title；需求必须填写
非空 statement；禁止使用“未命名”、空字符串或只写 id。每个场景必须填写 scenario_type，五类至少各一项。
所有内容标注 source_region_ids、confidence、assumptions 和 rationale；不确定内容放入 open_questions。
同一项目内可以把多个需求串联到场景、功能、逻辑组件、物理组件和接口；不要生成指向输入之外
或不存在对象的关系。对于宽泛的设计意图，额外给出 concept_proposal：提出可执行的概念方向、
可选方案、理由、假设和仍需确认的问题；如果能够基于常识给出参数初值，放入
parameter_suggestions，并明确它们只是 inferred/suggested 候选，不是用户确认值或验证结论。
不要因为输入信息不完整而拒绝回答，也不要把没有依据的行业固定参数写成已确认事实。
内容简洁、结构化、可追溯，不输出 JSON 之外的解释文字。"""


def _clone(value: object) -> object:
    return json.loads(canonical_json(value))


def _list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


_MISSING_LABELS = frozenset(
    {
        "未命名",
        "未命名场景",
        "未命名需求",
        "未命名需要",
        "未命名关注点",
        "未命名利益相关方",
        "未命名架构元素",
        "unknown",
        "unnamed",
    }
)
_SCENARIO_LABELS = {
    "normal": "正常运行场景",
    "boundary": "边界条件场景",
    "failure": "故障处置场景",
    "recovery": "恢复运行场景",
    "misuse": "误操作防护场景",
}
_CATEGORY_LABELS = {
    "end_user": "最终使用者",
    "clinician": "专业使用者",
    "operator": "系统运营方",
    "manufacturer": "制造与维护方",
    "regulatory_authority": "监管机构",
    "maintainer": "维护人员",
}


def _raw_text(raw: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(raw.get(key, "")).strip()
        if value and value.casefold() not in _MISSING_LABELS:
            return value
    return ""


def _project_label(state: dict[str, object]) -> str:
    context = state.get("system_context")
    if isinstance(context, dict):
        value = _raw_text(context, "name")
        if value and not value.startswith("待命名"):
            return value
    regions = state.get("document_regions") or state.get("spans") or []
    if isinstance(regions, list):
        for region in regions:
            if isinstance(region, dict):
                text = " ".join(str(region.get("text", "")).split())
                if text:
                    return text[:24]
    return "当前项目"


def _fallback_label(
    state: dict[str, object], section: str, raw: dict[str, object], index: int
) -> str:
    project = _project_label(state)
    if section == "stakeholder":
        category = _raw_text(raw, "category", "kind", "type")
        return _CATEGORY_LABELS.get(category, f"{project}相关方{index + 1}")
    if section == "concern":
        return f"{project}关注点{index + 1}"
    if section == "need":
        return f"满足{project}目标的需要{index + 1}"
    if section == "requirement":
        return f"系统应满足：{project}"
    if section == "scenario":
        scenario_type = _raw_text(raw, "scenario_type", "type") or "normal"
        return _SCENARIO_LABELS.get(scenario_type.casefold(), f"{project}运行场景{index + 1}")
    return f"{project}{section}{index + 1}"


def _workspace(state: dict[str, object]) -> str:
    scope = state.get("project_scope")
    return str(scope.get("workspace", "")) if isinstance(scope, dict) else ""


def _input_hash(state: dict[str, object]) -> str:
    scope = state.get("project_scope")
    if isinstance(scope, dict) and str(scope.get("input_hash", "")):
        return str(scope["input_hash"])
    regions = state.get("document_regions") or state.get("spans") or []
    return canonical_hash(
        tuple(
            (str(item.get("id", "")), str(item.get("text", "")))
            for item in regions
            if isinstance(item, dict)
        )
    )


def _region_ids(state: dict[str, object]) -> tuple[str, ...]:
    values = state.get("document_regions") or state.get("spans") or []
    return tuple(str(item.get("id", "")) for item in values if isinstance(item, dict) and item.get("id"))


def _source_span(state: dict[str, object], raw: dict[str, object] | None = None) -> str:
    raw = raw or {}
    source = str(raw.get("source_span_id") or raw.get("source_region_id") or "").strip()
    if not source:
        source_values = _strings(raw.get("source_span_ids") or raw.get("source_region_ids"))
        source = source_values[0] if source_values else ""
    if source.startswith("region-"):
        source = source.replace("region-", "span-", 1)
    if source:
        return source
    spans = state.get("spans") or []
    if isinstance(spans, list) and spans and isinstance(spans[0], dict):
        return str(spans[0].get("id", ""))
    regions = _region_ids(state)
    return regions[0].replace("region-", "span-", 1) if regions else "input"


def build_project_analysis_request(
    state: dict[str, object], config: object | None = None
) -> GenerationRequest:
    """Build the single project request with optional common-domain guidance.

    The default request deliberately contains no domain pack.  An enriched
    private ``guidance`` value is accepted for the explicit configuration path
    but is never persisted as raw prompt text in the workbench.
    """

    analysis_config = normalize_analysis_config(
        config if config is not None else state.get("analysis_config")
    )

    regions = state.get("document_regions") or state.get("spans") or []
    input_regions = [
        {
            "id": str(item.get("id", "")),
            "text": str(item.get("text", "")),
            "locator": str(item.get("locator", "")),
        }
        for item in regions
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    current_requirements = [
        {
            "id": str(item.get("id", "")),
            "subject": str(item.get("subject", "")),
            "predicate": str(item.get("predicate", "")),
            "object": str(item.get("object", item.get("statement", ""))),
            "status": str(item.get("status", "")),
        }
        for item in state.get("claims", ())
        if isinstance(item, dict) and item.get("status") != "rejected"
    ][:24]
    manual_stakeholders = [
        {key: item.get(key) for key in ("id", "name", "category", "goals", "interactions")}
        for item in state.get("stakeholders", ())
        if isinstance(item, dict) and item.get("producer") == "user"
    ]
    manual_scenarios = [
        {
            key: item.get(key)
            for key in ("id", "title", "description", "actors", "steps", "requirement_ids")
        }
        for item in state.get("scenarios", ())
        if isinstance(item, dict) and item.get("producer") == "user"
    ]
    scope = state.get("project_scope") if isinstance(state.get("project_scope"), dict) else {}
    user_payload: dict[str, object] = {
        "project_scope": {
            "workspace": str(scope.get("workspace", "")),
            "input_hash": _input_hash(state),
        },
        "analysis_config": {
            "enabled": bool(analysis_config["enabled"]),
            "domain_pack_id": analysis_config["domain_pack_id"],
            "domain_pack_version": analysis_config["domain_pack_version"],
            "base_pack_id": analysis_config["base_pack_id"],
            "industry_pack_ids": analysis_config["industry_pack_ids"],
            "discipline_pack_ids": analysis_config["discipline_pack_ids"],
            "overlay_pack_ids": analysis_config["overlay_pack_ids"],
        },
        "input_regions": input_regions,
        "current_requirements": current_requirements,
        "manual_stakeholders": manual_stakeholders,
        "manual_scenarios": manual_scenarios,
        "scenario_types": sorted(SCENARIO_TYPES),
        "limits": dict(_LIMITS),
    }
    if analysis_config["enabled"] and isinstance(config, dict):
        guidance = config.get("guidance")
        if isinstance(guidance, dict):
            user_payload["domain_guidance"] = guidance

    return GenerationRequest(
        lens_id=PROJECT_ANALYSIS_LENS,
        system_prompt=_SYSTEM_PROMPT,
        user_payload=user_payload,
        response_schema=_RESPONSE_SCHEMA,
        max_tokens=5200,
    )


def _stable_id(state: dict[str, object], section: str, raw_id: object, label: object) -> str:
    return f"llm-{section}-{canonical_hash((_workspace(state), _input_hash(state), str(raw_id), str(label)))[:12]}"


def _new_item(
    state: dict[str, object],
    section: str,
    raw: dict[str, object],
    payload: dict[str, object],
    raw_id: object,
    label: object,
) -> dict[str, object]:
    return {
        **payload,
        "id": _stable_id(state, section, raw_id, label),
        "status": "accepted",
        "producer": "llm",
        "candidate_type": "inferred",
        "analysis_input_hash": _input_hash(state),
        "project_workspace": _workspace(state),
        "confidence": float(raw.get("confidence", 0.7) or 0.7),
        "assumptions": _strings(raw.get("assumptions")),
        "rationale": str(raw.get("rationale", "当前项目输入的 LLM 推断")),
    }


def merge_auto_items(existing: object, incoming: list[dict[str, object]]) -> list[dict[str, object]]:
    """Replace prior LLM items while preserving user and explicit-pack data."""

    values = [
        dict(item)
        for item in existing
        if isinstance(item, dict) and str(item.get("producer", "")) != "llm"
    ] if isinstance(existing, (list, tuple)) else []
    values.extend(dict(item) for item in incoming)
    return sorted(values, key=lambda item: (str(item.get("name", item.get("statement", item.get("object", "")))), str(item.get("id", ""))))


def preserve_manual_and_replace_auto(
    existing: object, incoming: list[dict[str, object]], input_hash: str
) -> list[dict[str, object]]:
    """Keep manual/explicit scenarios and replace all current LLM scenarios."""

    del input_hash  # The item hash is retained on each generated scenario for auditability.
    values = [
        dict(item)
        for item in existing
        if isinstance(item, dict) and str(item.get("producer", "")) != "llm"
    ] if isinstance(existing, (list, tuple)) else []
    values.extend(dict(item) for item in incoming)
    return sorted(values, key=lambda item: (str(item.get("scenario_type", "")), str(item.get("title", "")), str(item.get("id", ""))))


def _map_ids(items: Iterable[dict[str, object]], normalized: list[dict[str, object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw, item in zip(items, normalized):
        if raw.get("id") is not None:
            result[str(raw["id"])] = str(item["id"])
    return result


def _ref(value: object, mapping: dict[str, str], valid: set[str]) -> str:
    text = str(value or "")
    mapped = mapping.get(text, text)
    return mapped if mapped in valid else ""


def _candidate(
    element_type: str,
    payload: dict[str, object],
    source_id: str,
    rationale: str,
    confidence: float,
) -> dict[str, object]:
    return CandidateEnvelope.create(
        element_type=element_type,
        pack_id=PROJECT_ANALYSIS_PACK_MARKER,
        payload=payload,
        provenance=(ProvenanceRef("inferred", source_id or "project-input", rationale),),
        producer="llm",
        confidence=max(0.0, min(1.0, confidence)),
        status="accepted",
    ).as_dict()


def build_project_graph(candidate_items: list[dict[str, object]]) -> dict[str, object]:
    ids = {str(item.get("id", "")) for item in candidate_items}
    elements = []
    relations = []
    for item in candidate_items:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        name = str(payload.get("name") or payload.get("title") or payload.get("statement") or "未命名")
        elements.append({
            "id": str(item.get("id", "")),
            "kind": str(item.get("element_type", "")),
            "name": name,
            "status": str(item.get("status", "accepted")),
            "attributes": payload,
            "producer": str(item.get("producer", "llm")),
            "provenance": item.get("provenance", []),
        })
        for relation in payload.get("relations", ()) if isinstance(payload, dict) else ():
            if not isinstance(relation, dict):
                continue
            source_id = str(relation.get("source_id", ""))
            target_id = str(relation.get("target_id", ""))
            if source_id in ids and target_id in ids:
                relations.append({
                    "source_id": source_id,
                    "predicate": str(relation.get("predicate", "relatedTo")),
                    "target_id": target_id,
                })
    return {
        "elements": sorted(elements, key=lambda item: (item["kind"], item["name"], item["id"])),
        "relations": sorted(relations, key=lambda item: (item["source_id"], item["predicate"], item["target_id"])),
        "graph_hash": canonical_hash({"elements": elements, "relations": relations}),
    }


def _normalize_scenarios(
    state: dict[str, object], raw_items: list[dict[str, object]], requirement_map: dict[str, str]
) -> list[dict[str, object]]:
    normalized = []
    for index, raw in enumerate(raw_items[: _LIMITS["scenarios"]]):
        scenario_type = str(raw.get("scenario_type", "normal")).strip().casefold()
        if scenario_type not in SCENARIO_TYPES:
            scenario_type = "normal"
        title = _raw_text(raw, "title", "name", "label", "scenario", "objective")
        title = title or _fallback_label(
            state, "scenario", {**raw, "scenario_type": scenario_type}, index
        )
        requirement_ids = sorted({
            value
            for value in (_ref(item, requirement_map, set(requirement_map.values())) for item in _strings(raw.get("requirement_ids")))
            if value
        })
        payload = {
            "title": title,
            "description": str(raw.get("description") or f"围绕当前项目目标执行：{title}"),
            "actors": _strings(raw.get("actors")),
            "preconditions": _strings(raw.get("preconditions")),
            "steps": _strings(raw.get("steps")) or ["识别当前场景条件", "执行系统任务", "确认结果或进入安全处置"],
            "expected_outcomes": _strings(raw.get("expected_outcomes") or raw.get("expected_outcome")) or ["完成当前项目目标或进入可控状态"],
            "faults": _strings(raw.get("faults") or raw.get("hazards")),
            "requirement_ids": requirement_ids,
            "scenario_type": scenario_type,
            "contexts": raw.get("contexts") if isinstance(raw.get("contexts"), dict) else {},
        }
        item = _new_item(state, "scenario", raw, payload, raw.get("id", title), title)
        item["generation_mode"] = "llm-project-analysis"
        item["generated_from"] = _input_hash(state)
        item["revision"] = 1
        item["review_history"] = []
        item["hash"] = canonical_hash(payload)
        normalized.append(item)
    return normalized


def _normalize_architecture(
    state: dict[str, object], raw_architecture: object, requirement_map: dict[str, str]
) -> tuple[dict[str, object], dict[str, str]]:
    architecture = raw_architecture if isinstance(raw_architecture, dict) else {}
    section_specs = (
        ("functions", "function", "F"),
        ("logical_components", "logical-component", "L"),
        ("physical_components", "physical-component", "P"),
        ("interfaces", "interface", "L"),
    )
    result: dict[str, object] = {key: [] for key, _, _ in section_specs}
    raw_id_map: dict[str, str] = {}
    node_count = 0
    for key, kind, layer in section_specs:
        values = _list(architecture.get(key))
        normalized = []
        for raw in values:
            if node_count >= _LIMITS["architecture_nodes"]:
                break
            name = _raw_text(raw, "name", "title", "label", "component", "function")
            name = name or _fallback_label(state, f"{kind}-element", raw, node_count)
            raw_requirement_ids = _strings(
                raw.get("requirement_ids") or raw.get("source_requirement_ids")
            )
            item = _new_item(state, key.rstrip("s"), raw, {
                "name": name,
                "kind": kind,
                "layer": layer,
                "description": str(raw.get("description", "")),
                "responsibilities": _strings(raw.get("responsibilities") or raw.get("inputs")),
                "interfaces": _strings(raw.get("interfaces")),
                "requirement_ids": sorted({
                    mapped
                    for value in raw_requirement_ids
                    for mapped in [_ref(value, requirement_map, set(requirement_map.values()))]
                    if mapped
                }),
                "source_requirement_ids": sorted({
                    mapped
                    for value in raw_requirement_ids
                    for mapped in [_ref(value, requirement_map, set(requirement_map.values()))]
                    if mapped
                }),
            }, raw.get("id", name), name)
            item["layer"] = layer
            item["kind"] = kind
            normalized.append(item)
            if raw.get("id") is not None:
                raw_id_map[str(raw["id"])] = str(item["id"])
            node_count += 1
        result[key] = normalized

    for raw, item in zip(_list(architecture.get("interfaces")), result["interfaces"]):
        source_id = raw_id_map.get(str(raw.get("source_id", "")), "")
        target_id = raw_id_map.get(str(raw.get("target_id", "")), "")
        if source_id:
            item["source_id"] = source_id
        if target_id:
            item["target_id"] = target_id

    relations = []
    for raw in _list(architecture.get("relations"))[: _LIMITS["relations"]]:
        source_id = raw_id_map.get(str(raw.get("source_id", "")), "")
        target_id = raw_id_map.get(str(raw.get("target_id", "")), "")
        if source_id and target_id:
            relations.append({
                "source_id": source_id,
                "predicate": str(raw.get("predicate", "relatedTo")),
                "target_id": target_id,
            })
    result["relations"] = relations
    return result, raw_id_map


def _normalize_concept_enrichment(
    state: dict[str, object], raw_proposal: object
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Normalize optional concept guidance without treating it as a requirement."""

    raw = raw_proposal if isinstance(raw_proposal, dict) else {}
    proposal = {
        "summary": _raw_text(raw, "summary", "title", "concept"),
        "alternatives": _strings(raw.get("alternatives") or raw.get("options")),
        "rationale": _strings(raw.get("rationale") or raw.get("reasons")),
        "assumptions": _strings(raw.get("assumptions")),
        "open_questions": _strings(raw.get("open_questions")),
    }
    suggestions: list[dict[str, object]] = []
    raw_suggestions = raw.get("parameter_suggestions")
    if isinstance(raw_suggestions, (list, tuple)):
        for index, item in enumerate(raw_suggestions[:48]):
            if not isinstance(item, dict):
                continue
            name = _raw_text(item, "name", "parameter", "field")
            if not name or item.get("value") in (None, ""):
                continue
            suggestion = {
                "id": _stable_id(state, "parameter-suggestion", item.get("id", name), name),
                "name": name,
                "value": item.get("value"),
                "unit": _raw_text(item, "unit"),
                "minimum": item.get("minimum"),
                "maximum": item.get("maximum"),
                "reason": _raw_text(item, "reason", "rationale") or "LLM 基于当前设计意图给出的初始估计",
                "status": "candidate",
                "producer": "llm",
                "candidate_type": "suggested",
                "analysis_input_hash": _input_hash(state),
                "project_workspace": _workspace(state),
                "confidence": float(item.get("confidence", 0.45) or 0.45),
                "source_region_ids": _strings(item.get("source_region_ids")) or list(_region_ids(state)[:1]),
            }
            suggestions.append(suggestion)
    proposal["parameter_suggestions"] = suggestions
    if not any(proposal.values()):
        return {}, []
    proposal["producer"] = "llm"
    proposal["candidate_type"] = "inferred"
    proposal["status"] = "candidate"
    proposal["analysis_input_hash"] = _input_hash(state)
    proposal["project_workspace"] = _workspace(state)
    return proposal, suggestions


def apply_project_analysis(
    state: dict[str, object], response: GenerationResponse
) -> dict[str, object]:
    """Normalize one valid LLM response into the current project workbench."""

    payload = response.payload
    if not isinstance(payload, dict):
        raise ContractViolation("LLM 项目分析结果必须是 JSON 对象")
    result = _clone(state)
    if not isinstance(result, dict):
        raise ContractViolation("requirements workbench state must be an object")
    result["analysis_config"] = normalize_analysis_config(
        result.get("analysis_config")
    )
    raw_stakeholders = _list(payload.get("stakeholders"))[: _LIMITS["stakeholders"]]
    raw_concerns = _list(payload.get("concerns"))[: _LIMITS["concerns"]]
    raw_needs = _list(payload.get("needs"))[: _LIMITS["needs"]]
    raw_requirements = _list(payload.get("requirements"))[: _LIMITS["requirements"]]

    stakeholder_items = []
    for index, raw in enumerate(raw_stakeholders):
        name = _raw_text(
            raw, "name", "label", "role", "actor", "organization", "stakeholder", "entity"
        ) or _fallback_label(result, "stakeholder", raw, index)
        category = _raw_text(raw, "category", "kind", "type") or "other"
        stakeholder_items.append(
            _new_item(
                result,
                "stakeholder",
                raw,
                {
                    "name": name,
                    "category": category,
                    "category_label": _raw_text(
                        raw, "category_label", "category", "kind", "type"
                    ) or "其他",
                    "goals": _strings(raw.get("goals") or raw.get("objectives")),
                    "interactions": _strings(raw.get("interactions") or raw.get("touchpoints")),
                    "source_span_id": _source_span(result, raw),
                },
                raw.get("id", name),
                name,
            )
        )
    stakeholder_map = _map_ids(raw_stakeholders, stakeholder_items)
    stakeholder_ids = set(item["id"] for item in stakeholder_items)

    concern_items = []
    for index, raw in enumerate(raw_concerns):
        stakeholder_id = _ref(raw.get("stakeholder_id"), stakeholder_map, stakeholder_ids)
        name = _raw_text(
            raw, "name", "label", "focus", "risk", "concern", "issue", "value"
        ) or _fallback_label(result, "concern", raw, index)
        concern_items.append(
            _new_item(
                result,
                "concern",
                raw,
                {
                    "name": name,
                    "stakeholder_id": stakeholder_id,
                    "source_span_id": _source_span(result, raw),
                },
                raw.get("id", name),
                name,
            )
        )
    concern_map = _map_ids(raw_concerns, concern_items)
    concern_ids = set(item["id"] for item in concern_items)

    need_items = []
    for index, raw in enumerate(raw_needs):
        stakeholder_id = _ref(raw.get("stakeholder_id"), stakeholder_map, stakeholder_ids)
        concern_id = _ref(raw.get("concern_id"), concern_map, concern_ids)
        name = _raw_text(
            raw, "name", "statement", "need", "desired_outcome", "value"
        ) or _fallback_label(result, "need", raw, index)
        statement = _raw_text(
            raw, "statement", "need", "desired_outcome", "value", "name"
        ) or f"需要满足{_project_label(result)}目标"
        need_items.append(
            _new_item(
                result,
                "need",
                raw,
                {
                    "name": name,
                    "statement": statement,
                    "value": _raw_text(
                        raw, "value", "statement", "need", "desired_outcome", "name"
                    ) or statement,
                    "stakeholder_id": stakeholder_id,
                    "concern_id": concern_id,
                    "source_span_id": _source_span(result, raw),
                },
                raw.get("id", name),
                statement,
            )
        )
    need_map = _map_ids(raw_needs, need_items)
    need_ids = set(item["id"] for item in need_items)

    requirement_items = []
    claim_items = []
    requirement_map: dict[str, str] = {}
    first_region = _region_ids(result)[0] if _region_ids(result) else ""
    for index, raw in enumerate(raw_requirements):
        statement = _raw_text(
            raw, "statement", "object", "text", "requirement", "description", "constraint"
        ) or _fallback_label(result, "requirement", raw, index)
        structured_id = _stable_id(result, "requirement", raw.get("id", statement), statement)
        claim_id = _stable_id(result, "claim", raw.get("id", statement), statement)
        requirement_map[str(raw.get("id", statement))] = claim_id
        source_region_id = str(raw.get("source_region_id") or first_region)
        requirement = _new_item(
            result,
            "requirement",
            raw,
            {
                "id": structured_id,
                "statement": statement,
                "subject": _raw_text(raw, "subject", "actor") or "系统",
                "predicate": _raw_text(raw, "predicate", "modality") or "应",
                "source_region_id": source_region_id,
                "source_type": str(raw.get("source_type", "inferred")),
                "verification_method": _raw_text(raw, "verification_method", "verification") or "analysis",
                "bulk_approvable": True,
            },
            raw.get("id", statement),
            statement,
        )
        requirement_items.append(requirement)
        claim_items.append({
            "id": claim_id,
            "span_id": source_region_id.replace("region-", "span-", 1),
            "subject": requirement["subject"],
            "predicate": requirement["predicate"],
            "object": statement,
            "confidence": requirement["confidence"],
            "status": "accepted",
            "source_type": "inferred",
            "candidate_type": "inferred",
            "interpretation": "LLM 项目需求候选",
            "need_id": _ref(raw.get("need_id"), need_map, need_ids) or None,
            "structured_requirement_id": structured_id,
            "producer": "llm",
            "bulk_approvable": True,
            "analysis_input_hash": _input_hash(result),
            "project_workspace": _workspace(result),
        })

    scenario_items = _normalize_scenarios(result, _list(payload.get("scenarios")), requirement_map)
    architecture, _architecture_ids = _normalize_architecture(
        result, payload.get("architecture"), requirement_map
    )

    candidate_items: list[dict[str, object]] = []
    candidate_groups = (
        ("stakeholder", stakeholder_items),
        ("concern", concern_items),
        ("need", need_items),
        ("requirement", requirement_items),
        ("operational_scenario", scenario_items),
    )
    for element_type, items in candidate_groups:
        for item in items:
            payload_item = dict(item)
            item_id = str(payload_item.pop("id"))
            candidate_items.append(
                _candidate(
                    element_type,
                    payload_item,
                    item_id,
                    str(item.get("rationale", "当前项目输入的 LLM 推断")),
                    float(item.get("confidence", 0.7)),
                )
            )
    for key, items in architecture.items():
        if key == "relations":
            continue
        for item in items if isinstance(items, list) else []:
            payload_item = dict(item)
            item_id = str(payload_item.pop("id"))
            candidate_items.append(
                _candidate(
                    str(item.get("kind", key)),
                    payload_item,
                    item_id,
                    str(item.get("rationale", "当前项目输入的 LLM 架构推断")),
                    float(item.get("confidence", 0.7)),
                )
            )

    discovery = result.get("discovery") if isinstance(result.get("discovery"), dict) else {}
    discovery = dict(discovery)
    discovery["candidate_sets"] = [{
        "lens_id": PROJECT_ANALYSIS_LENS,
        "input_hash": _input_hash(result),
        "output_hash": response.output_hash,
        "provider_id": response.provider_id,
        "model_id": response.model_id,
        "items": candidate_items,
    }]
    discovery["accepted_graph"] = build_project_graph(candidate_items)
    discovery["architecture"] = architecture
    discovery["coverage"] = {}
    discovery["diagnostics"] = [
        item for item in discovery.get("diagnostics", ())
        if isinstance(item, dict) and item.get("code") != "generative_model_unavailable"
    ]
    discovery["diagnostics"].extend(_list(payload.get("diagnostics")))
    discovery["revision"] = int(discovery.get("revision", 0)) + 1
    result["discovery"] = discovery
    system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
    current_context = result.get("system_context") if isinstance(result.get("system_context"), dict) else {}
    result["system_context"] = {
        **current_context,
        "name": str(system.get("name") or current_context.get("name") or "待命名系统"),
        "domain": str(system.get("domain") or current_context.get("domain") or "未分类"),
        "mission": str(system.get("mission") or ""),
        "source_text": "\n".join(str(item.get("text", "")) for item in result.get("document_regions", ()) if isinstance(item, dict)),
        "status": "formal-candidate",
        "confidence": float(system.get("confidence", 0.8) or 0.8),
    }
    result["stakeholders"] = merge_auto_items(result.get("stakeholders"), stakeholder_items)
    result["concerns"] = merge_auto_items(result.get("concerns"), concern_items)
    result["needs"] = merge_auto_items(result.get("needs"), need_items)
    result["structured_requirements"] = merge_auto_items(result.get("structured_requirements"), requirement_items)
    rule_claims = [
        item
        for item in result.get("claims", ())
        if claim_items
        and not (
            isinstance(item, dict)
            and item.get("producer") == "rule"
            and item.get("source_type") in {"goal", "provisional"}
        )
    ] if claim_items else [dict(item) for item in result.get("claims", ()) if isinstance(item, dict)]
    result["claims"] = merge_auto_items(rule_claims, claim_items)
    result["scenarios"] = preserve_manual_and_replace_auto(result.get("scenarios"), scenario_items, _input_hash(result))
    result["discovery"]["open_questions"] = _strings(payload.get("open_questions"))[:24]
    concept_proposal, parameter_suggestions = _normalize_concept_enrichment(
        result, payload.get("concept_proposal")
    )
    result["concept_enrichment"] = {
        "proposal": concept_proposal,
        "parameter_suggestions": parameter_suggestions,
        "provider_id": response.provider_id,
        "model_id": response.model_id,
        "input_hash": response.input_hash,
        "output_hash": response.output_hash,
    }
    result["auto_analysis"] = {
        "status": "completed",
        "mode": "llm-project-analysis",
        "workspace": _workspace(result),
        "input_hash": _input_hash(result),
        "domain_pack": {
            "id": result["analysis_config"]["domain_pack_id"],
            "version": result["analysis_config"]["domain_pack_version"],
        }
        if result["analysis_config"]["enabled"]
        else None,
        "modules": {
            "stakeholders": len(stakeholder_items),
            "concerns": len(concern_items),
            "needs": len(need_items),
            "structured_requirements": len(requirement_items),
            "scenarios": len(scenario_items),
            "rflp": False,
            "mbse": False,
        },
        "diagnostics": list(discovery["diagnostics"]),
    }
    result["rflp"] = None
    result["coverage"] = {}
    result["svg"] = ""
    result["draft"] = False
    result["draft_graph"] = None
    result["draft_warnings"] = []
    result["mbse"] = None
    result["baseline"] = None
    result["project"] = None
    result["flow"] = None
    return sync_review_queue(result)


def mark_llm_waiting(state: dict[str, object], message: str) -> dict[str, object]:
    """Keep explicit/rule data visible while refusing fabricated domain output."""

    result = _clone(state)
    if not isinstance(result, dict):
        raise ContractViolation("requirements workbench state must be an object")
    result["analysis_config"] = normalize_analysis_config(
        result.get("analysis_config")
    )
    result["auto_analysis"] = {
        "status": "waiting_for_llm",
        "mode": "llm-project-analysis",
        "workspace": _workspace(result),
        "input_hash": _input_hash(result),
        "domain_pack": {
            "id": result["analysis_config"]["domain_pack_id"],
            "version": result["analysis_config"]["domain_pack_version"],
        }
        if result["analysis_config"]["enabled"]
        else None,
        "modules": {
            "stakeholders": 0,
            "concerns": 0,
            "needs": 0,
            "structured_requirements": 0,
            "scenarios": 0,
            "rflp": False,
            "mbse": False,
        },
        "diagnostics": [{"code": "project_llm_unavailable", "severity": "warning", "message": message}],
    }
    discovery = result.get("discovery") if isinstance(result.get("discovery"), dict) else {}
    discovery = dict(discovery)
    discovery["candidate_sets"] = []
    discovery["accepted_graph"] = {"elements": [], "relations": []}
    discovery["architecture"] = {}
    discovery["coverage"] = {}
    diagnostics = [item for item in discovery.get("diagnostics", ()) if isinstance(item, dict)]
    diagnostics.append({"code": "project_llm_unavailable", "severity": "warning", "message": message})
    discovery["diagnostics"] = diagnostics
    result["discovery"] = discovery
    result["scenarios"] = [
        item for item in result.get("scenarios", ())
        if not isinstance(item, dict) or str(item.get("producer", "")) != "llm"
    ]
    result["rflp"] = None
    result["mbse"] = None
    result["baseline"] = None
    result["project"] = None
    result["svg"] = ""
    return sync_review_queue(result)
