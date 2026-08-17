"""Small, schema-bounded project-analysis requests and deterministic merging."""

from __future__ import annotations

import json
from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse


@dataclass(frozen=True, slots=True)
class AnalysisBlock:
    id: str
    max_items: int
    max_tokens: int
    response_schema: dict[str, object]


_BLOCK_SPECS = (
    ("system_scope", 4, 500, "system_scope：明确系统边界、任务目标、运行环境和未知前提。"),
    ("stakeholders", 12, 1200, "stakeholders：识别与系统目标、使用、运营、监管、供应和环境有关的利益相关方。"),
    ("concerns_needs", 18, 1400, "concerns_needs：为已识别利益相关方补充关注点和可追溯需要，不生成架构。"),
    ("requirements", 16, 1600, "requirements：把明确目标和需要转成短小、可验证、可追溯的需求。"),
    ("scenarios", 10, 1400, "scenarios：生成正常、边界、故障、恢复和误操作场景，不生成架构。"),
    ("architecture", 18, 1600, "architecture：基于已接受需求给出功能、逻辑组件、物理组件和接口候选。"),
)
_BLOCK_TASKS = {item[0]: item[3] for item in _BLOCK_SPECS}
_BLOCK_MAX_ITEMS = {item[0]: item[1] for item in _BLOCK_SPECS}


def _schema(max_items: int) -> dict[str, object]:
    return {
        "type": "object",
        "required": ["items", "diagnostics"],
        "properties": {
            "items": {
                "type": "array",
                "maxItems": max_items,
                "items": {"type": "object", "additionalProperties": True},
            },
            "diagnostics": {"type": "array", "items": {"type": "object"}},
        },
        "additionalProperties": False,
    }


def build_analysis_blocks(
    state: dict[str, object], composed_pack: dict[str, object]
) -> tuple[AnalysisBlock, ...]:
    del state, composed_pack
    return tuple(
        AnalysisBlock(block_id, max_items, max_tokens, _schema(max_items))
        for block_id, max_items, max_tokens, _task in _BLOCK_SPECS
    )


def _input_hash(state: dict[str, object]) -> str:
    scope = state.get("project_scope")
    if isinstance(scope, dict) and str(scope.get("input_hash", "")):
        return str(scope["input_hash"])
    regions = state.get("document_regions") or state.get("spans") or []
    return canonical_hash(regions)


def _regions(state: dict[str, object]) -> list[dict[str, object]]:
    values = state.get("document_regions") or state.get("spans") or []
    return [
        {"id": str(item.get("id", "")), "text": str(item.get("text", ""))}
        for item in values
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ][:24]


def _accepted_requirements(state: dict[str, object]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    structured_ids: set[str] = set()
    for group in ("structured_requirements", "claims"):
        for item in (state.get(group, ()) if isinstance(state.get(group), (list, tuple)) else ()):
            if not isinstance(item, dict) or str(item.get("status", "")).casefold() != "accepted":
                continue
            item_id = str(item.get("id", "")).strip()
            linked_id = str(item.get("structured_requirement_id", "")).strip()
            if group == "claims" and linked_id and linked_id in structured_ids:
                continue
            values.append(
                {
                    "id": item_id,
                    "statement": str(item.get("statement", item.get("object", ""))),
                    "subject": str(item.get("subject", "")),
                    "status": "accepted",
                }
            )
            if group == "structured_requirements" and item_id:
                structured_ids.add(item_id)
    return sorted(values, key=lambda item: (str(item.get("id", "")), canonical_json(item)))[:32]


def _guidance(block_id: str, pack: dict[str, object]) -> dict[str, object]:
    fields = {
        "stakeholders": ("stakeholder_lenses", "coverage_rules"),
        "concerns_needs": ("stakeholder_lenses", "prompt_fragments"),
        "requirements": ("coverage_rules", "prompt_fragments"),
        "scenarios": ("scenario_dimensions", "coverage_rules", "prompt_fragments"),
        "architecture": ("lifecycle_phases", "coverage_rules", "prompt_fragments"),
        "system_scope": ("lifecycle_phases", "scenario_dimensions"),
    }[block_id]
    return {key: pack.get(key, {}) for key in fields if pack.get(key, {}) not in (None, {}, [])}


def build_block_request(
    state: dict[str, object], block: AnalysisBlock, composed_pack: dict[str, object]
) -> GenerationRequest:
    """Build one bounded request without carrying unrelated block instructions."""

    input_hash = _input_hash(state)
    payload = {
        "block_id": block.id,
        "input_hash": input_hash,
        "project_scope": state.get("project_scope", {}),
        "pack_ids": list(composed_pack.get("pack_ids", ())),
        "pack_hashes": composed_pack.get("pack_hashes", {}),
        "limits": {"max_items": block.max_items, "max_tokens": block.max_tokens},
        "task": _BLOCK_TASKS[block.id],
        "input_regions": _regions(state),
        "accepted_requirements": _accepted_requirements(state),
        "pack_guidance": _guidance(block.id, composed_pack),
    }
    prompt = (
        "你是一个严格的 MBSE 分析块。只完成当前 task，返回 response_schema 对象；"
        "items 最多达到 limits.max_items，内容简短、可追溯，不要解释 JSON。"
    )
    return GenerationRequest(
        lens_id=f"project_analysis.{block.id}",
        system_prompt=prompt,
        user_payload=payload,
        response_schema=block.response_schema,
        max_tokens=block.max_tokens,
    )


def _clone(value: object) -> object:
    return json.loads(canonical_json(value))


def _label(raw: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(raw.get(key, "")).strip()
        if value:
            return value
    return ""


def _stable_id(state: dict[str, object], block_id: str, raw: dict[str, object], label: str) -> str:
    scope = state.get("project_scope")
    workspace = str(scope.get("workspace", "")) if isinstance(scope, dict) else ""
    raw_id = str(raw.get("id", label))
    return f"llm-{block_id}-{canonical_hash((workspace, _input_hash(state), block_id, raw_id, label))[:12]}"


def _remove_block_items(values: object, block_id: str, input_hash: str) -> list[dict[str, object]]:
    return [
        dict(item)
        for item in values
        if isinstance(item, dict)
        and not (
            item.get("producer") == "llm"
            and item.get("analysis_block_id") == block_id
            and item.get("analysis_input_hash") == input_hash
        )
    ] if isinstance(values, list) else []


def _new_item(state: dict[str, object], block_id: str, raw: dict[str, object], payload: dict[str, object], label: str) -> dict[str, object]:
    item = {
        **payload,
        "id": _stable_id(state, block_id, raw, label),
        "status": "accepted",
        "producer": "llm",
        "candidate_type": "inferred",
        "analysis_block_id": block_id,
        "analysis_input_hash": _input_hash(state),
        "project_workspace": str((state.get("project_scope") or {}).get("workspace", ""))
        if isinstance(state.get("project_scope"), dict)
        else "",
        "confidence": float(raw.get("confidence", 0.7) or 0.7),
        "assumptions": raw.get("assumptions", []) if isinstance(raw.get("assumptions"), list) else [],
        "rationale": str(raw.get("rationale", "当前项目输入的 LLM 分块推断")),
        "source_region_ids": [str(item.get("id")) for item in raw.get("source_regions", []) if isinstance(item, dict)]
        if isinstance(raw.get("source_regions"), list)
        else [str(item) for item in raw.get("source_region_ids", []) if str(item)],
    }
    source_item_id = str(raw.get("id", "")).strip()
    if source_item_id:
        # Keep the model's identifier so later blocks from the same legacy
        # response can refer to the newly normalized deterministic identifier.
        item["source_item_id"] = source_item_id
    return item


_SINGULAR_RELATIONS = ("stakeholder_id", "concern_id", "need_id", "requirement_id", "source_id", "target_id")
_LIST_RELATIONS = ("requirement_ids", "source_ids", "target_ids")


def _all_ids(state: dict[str, object]) -> set[str]:
    values: set[str] = set()
    for group in ("claims", "structured_requirements", "stakeholders", "concerns", "needs", "scenarios"):
        values.update(
            str(item.get("id"))
            for item in state.get(group, ())
            if isinstance(item, dict) and item.get("id")
        )
    discovery = state.get("discovery")
    architecture = discovery.get("architecture") if isinstance(discovery, dict) else {}
    if isinstance(architecture, dict):
        for key in ("functions", "logical_components", "physical_components", "interfaces", "items"):
            entries = architecture.get(key, ())
            iterable = entries if isinstance(entries, (list, tuple)) else ()
            values.update(
                str(item.get("id"))
                for item in iterable
                if isinstance(item, dict) and item.get("id")
            )
    return values


def _source_aliases(state: dict[str, object]) -> dict[str, str]:
    """Map model-provided ids to the deterministic ids stored in the state."""

    aliases: dict[str, str] = {}
    for group in (
        "claims",
        "structured_requirements",
        "stakeholders",
        "concerns",
        "needs",
        "scenarios",
    ):
        for item in state.get(group, ()):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_item_id", "")).strip()
            item_id = str(item.get("id", "")).strip()
            if source_id and item_id:
                aliases.setdefault(source_id, item_id)
    discovery = state.get("discovery")
    architecture = discovery.get("architecture") if isinstance(discovery, dict) else {}
    if isinstance(architecture, dict):
        for key in ("functions", "logical_components", "physical_components", "interfaces"):
            entries = architecture.get(key, ())
            for item in entries if isinstance(entries, (list, tuple)) else ():
                if not isinstance(item, dict):
                    continue
                source_id = str(item.get("source_item_id", "")).strip()
                item_id = str(item.get("id", "")).strip()
                if source_id and item_id:
                    aliases.setdefault(source_id, item_id)
    return aliases


def _mapped_id(value: object, aliases: dict[str, str], valid_ids: set[str]) -> str:
    raw = str(value or "").strip()
    mapped = aliases.get(raw, raw)
    return mapped if mapped in valid_ids else ""


def _filter_relations(
    item: dict[str, object], aliases: dict[str, str], valid_ids: set[str]
) -> dict[str, object]:
    result = dict(item)
    for key in _SINGULAR_RELATIONS:
        if key not in result:
            continue
        value = _mapped_id(result[key], aliases, valid_ids)
        if value:
            result[key] = value
        else:
            result.pop(key, None)
    for key in _LIST_RELATIONS:
        if key not in result:
            continue
        values = result[key] if isinstance(result[key], (list, tuple)) else ()
        filtered = sorted(
            {
                value
                for raw in values
                for value in (_mapped_id(raw, aliases, valid_ids),)
                if value
            }
        )
        if filtered:
            result[key] = filtered
        else:
            result.pop(key, None)
    relations = []
    for relation in (result.get("relations", ()) if isinstance(result.get("relations"), list) else ()):
        if not isinstance(relation, dict):
            continue
        source_id = _mapped_id(relation.get("source_id"), aliases, valid_ids)
        target_id = _mapped_id(relation.get("target_id"), aliases, valid_ids)
        if source_id and target_id:
            relations.append(
                {
                    "source_id": source_id,
                    "predicate": str(relation.get("predicate", "relatedTo")),
                    "target_id": target_id,
                }
            )
    if relations:
        result["relations"] = sorted(
            relations,
            key=lambda relation: (
                relation["source_id"], relation["predicate"], relation["target_id"]
            ),
        )
    elif "relations" in result:
        result.pop("relations", None)
    return result


def _architecture_bucket(raw: dict[str, object]) -> str | None:
    kind = str(raw.get("kind", raw.get("type", raw.get("layer", "")))).casefold()
    if kind in {"relation", "relations"}:
        return None
    if "interface" in kind:
        return "interfaces"
    if "logical" in kind or kind in {"l", "component"}:
        return "logical_components"
    if "physical" in kind or kind in {"p", "block"}:
        return "physical_components"
    return "functions"


def _merge_architecture(
    result: dict[str, object], raw_items: list[dict[str, object]], input_hash: str, block_id: str
) -> None:
    discovery = dict(result.get("discovery") or {})
    architecture = dict(discovery.get("architecture") or {})
    valid_ids = _all_ids(result)
    generated_nodes: list[tuple[dict[str, object], dict[str, object], str]] = []
    aliases: dict[str, str] = _source_aliases(result)
    relation_items: list[dict[str, object]] = []
    for raw in raw_items:
        bucket = _architecture_bucket(raw)
        if bucket is None:
            relation_items.append(raw)
            continue
        name = _label(raw, "name", "title", "function", "component", "description")
        if not name:
            continue
        payload = {
            key: value
            for key, value in raw.items()
            if key not in {"id", "relations", "source_region_ids", "source_regions"}
        }
        payload["name"] = name
        node = _new_item(result, block_id, raw, payload, name)
        generated_nodes.append((raw, node, bucket))
        if str(raw.get("id", "")).strip():
            aliases.setdefault(str(raw["id"]).strip(), str(node["id"]))
        aliases.setdefault(str(node["id"]), str(node["id"]))
    valid_ids.update(str(node["id"]) for _, node, _ in generated_nodes)
    for bucket in ("functions", "logical_components", "physical_components", "interfaces"):
        entries = architecture.get(bucket, ())
        iterable = entries if isinstance(entries, (list, tuple)) else ()
        architecture[bucket] = [
            dict(item)
            for item in iterable
            if isinstance(item, dict)
            and not (
                item.get("producer") == "llm"
                and item.get("analysis_block_id") == block_id
                and item.get("analysis_input_hash") == input_hash
            )
        ]
    for raw, node, bucket in generated_nodes:
        cleaned = _filter_relations(node, aliases, valid_ids)
        architecture.setdefault(bucket, [])
        current = list(architecture[bucket]) if isinstance(architecture[bucket], list) else []
        current.append(cleaned)
        architecture[bucket] = current
        for relation in (raw.get("relations", ()) if isinstance(raw.get("relations"), list) else ()):
            if isinstance(relation, dict):
                relation_items.append(relation)
    relations = [
        dict(item)
        for item in architecture.get("relations", ())
        if isinstance(item, dict)
        and not (
            item.get("producer") == "llm"
            and item.get("analysis_block_id") == block_id
            and item.get("analysis_input_hash") == input_hash
        )
    ]
    for relation in relation_items:
        source_id = _mapped_id(relation.get("source_id"), aliases, valid_ids)
        target_id = _mapped_id(relation.get("target_id"), aliases, valid_ids)
        if source_id and target_id:
            relations.append(
                {
                    "source_id": source_id,
                    "predicate": str(relation.get("predicate", "relatedTo")),
                    "target_id": target_id,
                    "producer": "llm",
                    "analysis_block_id": block_id,
                    "analysis_input_hash": input_hash,
                }
            )
    architecture["relations"] = sorted(
        {canonical_json(item): item for item in relations}.values(),
        key=lambda item: (
            str(item.get("source_id", "")),
            str(item.get("predicate", "")),
            str(item.get("target_id", "")),
        ),
    )
    for bucket in ("functions", "logical_components", "physical_components", "interfaces"):
        architecture[bucket] = sorted(
            [item for item in architecture.get(bucket, ()) if isinstance(item, dict)],
            key=lambda item: (str(item.get("name", "")), str(item.get("id", ""))),
        )
    architecture["block_id"] = block_id
    discovery["architecture"] = architecture
    result["discovery"] = discovery


def _items(response: GenerationResponse) -> list[dict[str, object]]:
    payload = response.payload
    if not isinstance(payload, dict):
        raise ContractViolation("LLM 分析块结果必须是对象")
    values = payload.get("items", [])
    if not values:
        block_id = str(response.lens_id).rsplit(".", 1)[-1]
        legacy_key = {
            "stakeholders": "stakeholders",
            "requirements": "requirements",
            "scenarios": "scenarios",
        }.get(block_id)
        if legacy_key:
            values = payload.get(legacy_key, [])
        elif block_id == "system_scope" and isinstance(payload.get("system"), dict):
            values = [payload["system"]]
        elif block_id == "concerns_needs":
            values = [
                {"concern": item.get("name", ""), **item}
                for item in payload.get("concerns", [])
                if isinstance(item, dict)
            ] + [
                {"statement": item.get("statement", ""), **item}
                for item in payload.get("needs", [])
                if isinstance(item, dict)
            ]
        elif block_id == "architecture" and isinstance(payload.get("architecture"), dict):
            architecture = payload["architecture"]
            values = []
            for key, kind in (
                ("functions", "function"),
                ("logical_components", "logical_component"),
                ("physical_components", "physical_component"),
                ("interfaces", "interface"),
            ):
                for item in (architecture.get(key, []) if isinstance(architecture.get(key), list) else []):
                    if isinstance(item, dict):
                        values.append({**item, "kind": kind})
            for item in (architecture.get("relations", []) if isinstance(architecture.get("relations"), list) else []):
                if isinstance(item, dict):
                    values.append({**item, "kind": "relation"})
    if not isinstance(values, list):
        raise ContractViolation("LLM 分析块 items 必须是数组")
    return [item for item in values if isinstance(item, dict)]


def merge_block_result(
    state: dict[str, object], block_id: str, response: GenerationResponse
) -> dict[str, object]:
    """Merge only this block and remove stale items from the same input hash."""

    if block_id not in _BLOCK_MAX_ITEMS:
        raise ContractViolation(f"未知分析块: {block_id}")
    result = _clone(state)
    payload = response.payload if isinstance(response.payload, dict) else {}
    input_hash = _input_hash(result)
    payload_input_hash = str(payload.get("input_hash", "")).strip()
    if payload_input_hash and payload_input_hash != input_hash:
        return result
    payload_block_id = str(payload.get("block_id", "")).strip()
    if payload_block_id and payload_block_id != block_id:
        return result
    valid_ids = _all_ids(result)
    raw_items = _items(response)[: _BLOCK_MAX_ITEMS[block_id]]
    if block_id == "system_scope":
        if raw_items:
            first = raw_items[0]
            current = result.get("system_context") if isinstance(result.get("system_context"), dict) else {}
            result["system_context"] = {
                **current,
                "name": _label(first, "name", "system_name", "title") or "当前项目",
                "domain": _label(first, "domain", "context") or "待补充领域",
                "mission": _label(first, "mission", "goal", "objective") or "待补充任务",
                "producer": "llm",
                "analysis_block_id": block_id,
                "analysis_input_hash": input_hash,
            }
        return result

    if block_id == "stakeholders":
        items = _remove_block_items(result.get("stakeholders"), block_id, input_hash)
        for raw in raw_items:
            name = _label(raw, "name", "label", "role", "stakeholder")
            if not name:
                continue
            items.append(_new_item(result, block_id, raw, {
                "name": name,
                "category": _label(raw, "category", "kind") or "other",
                "goals": raw.get("goals", []) if isinstance(raw.get("goals"), list) else [],
                "interactions": raw.get("interactions", []) if isinstance(raw.get("interactions"), list) else [],
            }, name))
        result["stakeholders"] = sorted(items, key=lambda item: (str(item.get("name", "")), str(item.get("id", ""))))
    elif block_id == "concerns_needs":
        concerns = _remove_block_items(result.get("concerns"), block_id, input_hash)
        needs = _remove_block_items(result.get("needs"), block_id, input_hash)
        incoming: list[tuple[str, dict[str, object], dict[str, object]]] = []
        for index, raw in enumerate(raw_items):
            concern_name = _label(raw, "concern", "concern_name")
            if concern_name:
                incoming.append(
                    (
                        "concern",
                        raw,
                        _new_item(result, block_id, raw, {"name": concern_name}, concern_name),
                    )
                )
            need_text = _label(raw, "statement", "need", "desired_outcome")
            if need_text:
                incoming.append(
                    (
                        "need",
                        raw,
                        _new_item(
                            result,
                            block_id,
                            raw,
                            {"name": _label(raw, "name") or f"需要{index + 1}", "statement": need_text},
                            need_text,
                        ),
                    )
                )
        aliases = _source_aliases(result)
        aliases.update(
            {
                str(raw.get("id")): str(item["id"])
                for _kind, raw, item in incoming
                if str(raw.get("id", "")).strip()
            }
        )
        valid_ids.update(str(item["id"]) for _kind, _raw, item in incoming)
        for kind, raw, item in incoming:
            cleaned = _filter_relations(
                {
                    **item,
                    **{
                        key: raw[key]
                        for key in ("stakeholder_id", "concern_id")
                        if key in raw
                    },
                },
                aliases,
                valid_ids,
            )
            (concerns if kind == "concern" else needs).append(cleaned)
        result["concerns"] = sorted(concerns, key=lambda item: (str(item.get("name", "")), str(item.get("id", ""))))
        result["needs"] = sorted(needs, key=lambda item: (str(item.get("statement", "")), str(item.get("id", ""))))
    elif block_id == "requirements":
        claims = _remove_block_items(result.get("claims"), block_id, input_hash)
        requirements = _remove_block_items(result.get("structured_requirements"), block_id, input_hash)
        for raw in raw_items:
            statement = _label(raw, "statement", "requirement", "text")
            if not statement:
                continue
            item = _new_item(result, block_id, raw, {"statement": statement, "subject": _label(raw, "subject") or "系统", "predicate": _label(raw, "predicate", "modality") or "应", "verification_method": _label(raw, "verification_method", "verification") or "analysis", "source_type": "inferred", "bulk_approvable": True}, statement)
            requirements.append(item)
            claims.append({**item, "object": statement, "span_id": (item.get("source_region_ids") or ["input"])[0].replace("region-", "span-", 1), "structured_requirement_id": item["id"], "interpretation": "LLM 分块需求推断"})
        result["claims"] = sorted(claims, key=lambda item: (str(item.get("object", "")), str(item.get("id", ""))))
        result["structured_requirements"] = sorted(requirements, key=lambda item: (str(item.get("statement", "")), str(item.get("id", ""))))
        valid_ids.update(str(item.get("id")) for item in requirements)
    elif block_id == "scenarios":
        scenarios = _remove_block_items(result.get("scenarios"), block_id, input_hash)
        for raw in raw_items:
            title = _label(raw, "title", "name", "scenario")
            if not title:
                continue
            scenario = _new_item(
                result,
                block_id,
                raw,
                {
                    "title": title,
                    "scenario_type": _label(raw, "scenario_type", "type") or "normal",
                    "actors": raw.get("actors", []) if isinstance(raw.get("actors"), list) else [],
                    "steps": raw.get("steps", []) if isinstance(raw.get("steps"), list) else [],
                    "expected_outcomes": raw.get("expected_outcomes", []) if isinstance(raw.get("expected_outcomes"), list) else [],
                    "requirement_ids": raw.get("requirement_ids", []) if isinstance(raw.get("requirement_ids"), list) else [],
                },
                title,
            )
            scenarios.append(_filter_relations(scenario, _source_aliases(result), valid_ids))
        result["scenarios"] = sorted(scenarios, key=lambda item: (str(item.get("scenario_type", "")), str(item.get("title", "")), str(item.get("id", ""))))
    elif block_id == "architecture":
        _merge_architecture(result, raw_items, input_hash, block_id)
    else:
        raise ContractViolation(f"未知分析块: {block_id}")

    discovery = dict(result.get("discovery") or {})
    block_results = dict(discovery.get("block_results") or {})
    block_results[block_id] = {"items": raw_items, "diagnostics": response.payload.get("diagnostics", []) if isinstance(response.payload, dict) else []}
    discovery["block_results"] = block_results
    result["discovery"] = discovery
    return result


__all__ = ["AnalysisBlock", "build_analysis_blocks", "build_block_request", "merge_block_result"]
