from __future__ import annotations

import json
import os
from dataclasses import asdict
from html import escape

from rflp_lite.adapters.readers import RuleClaimExtractor, read_artifact
from rflp_lite.adapters.llm_client import chat_completion
from rflp_lite.application.synthesize import synthesize_rflp
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import AdapterFailure, InvariantViolation
from rflp_lite.domain.models import Claim, ModelElement, Relation


_ROLE_ALIASES = {
    "内容编辑人员": ("内容编辑人员", "内容编辑者", "ContentEditor"),
    "内容管理员": ("内容管理员", "ContentAdmin"),
    "管理员": ("系统管理员", "后台管理员", "管理员", "AdminRole", "admin"),
    "普通用户": ("普通用户", "unauthorized_user", "end_user"),
    "审计人员": ("审计人员", "审核员", "Auditor"),
    "运维人员": ("运维人员", "运维", "Operator"),
    "数据负责人": ("数据负责人", "DataOwner", "data_owner"),
    "软件维护人员": ("软件维护人员", "维护人员", "Maintainer", "developer"),
    "项目负责人": ("项目负责人", "Approver", "product_owner"),
    "外部系统": ("外部系统", "第三方平台", "external_system"),
}
_GROUPS = {"stakeholders", "concerns", "needs", "claims"}
_STATUSES = {"candidate", "accepted", "rejected"}


def _clone(value: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(value))


def _id(prefix: str, *parts: object) -> str:
    return f"{prefix}-{canonical_hash(parts)[:12]}"


def _contains(text: str, alias: str) -> bool:
    lowered = text.casefold()
    value = alias.casefold()
    if value.isascii():
        padded = "".join(character if character.isalnum() else " " for character in lowered)
        return value.replace("_", " ") in padded
    return value in lowered


def _roles(text: str) -> tuple[str, ...]:
    matches = {
        canonical
        for canonical, aliases in _ROLE_ALIASES.items()
        for alias in sorted(aliases, key=len, reverse=True)
        if _contains(text, alias)
    }
    if "内容管理员" in matches:
        matches.discard("管理员")
    return tuple(sorted(matches))


def _concern(text: str) -> str:
    lowered = text.casefold()
    categories = (
        (("审计", "追踪", "audit", "trace"), "可审计性"),
        (("权限", "安全", "隐私", "authorize", "security", "privacy"), "数据安全"),
        (("恢复", "备份", "故障", "restore", "backup", "recover"), "故障恢复"),
        (("维护", "替换", "部署", "maintain", "replace", "deploy"), "可维护性"),
        (("性能", "延迟", "performance", "latency"), "性能"),
        (("成本", "周期", "cost", "schedule"), "成本与交付"),
    )
    return next(
        (name for words, name in categories if any(word in lowered for word in words)),
        "功能完整性",
    )


def analyze_artifact(filename: str, content: bytes) -> dict[str, object]:
    artifact, spans = read_artifact(filename, content)
    extracted_claims = RuleClaimExtractor().extract(spans)
    stakeholders: list[dict[str, object]] = []
    concerns: list[dict[str, object]] = []
    needs: list[dict[str, object]] = []
    stakeholder_by_span: dict[str, str] = {}
    need_by_span: dict[str, str] = {}

    for span in spans:
        for role in _roles(span.text):
            stakeholder_id = _id("stkc", role, span.id)
            concern_id = _id("concern", stakeholder_id, _concern(span.text))
            need_id = _id("need", stakeholder_id, span.text)
            stakeholder_by_span.setdefault(span.id, stakeholder_id)
            need_by_span.setdefault(span.id, need_id)
            stakeholders.append(
                {
                    "id": stakeholder_id,
                    "name": role,
                    "candidate_type": "explicit",
                    "source_span_id": span.id,
                    "confidence": 1.0,
                    "reason": "原文明确出现角色或角色标识符",
                    "producer": "rule",
                    "status": "candidate",
                }
            )
            concerns.append(
                {
                    "id": concern_id,
                    "name": _concern(span.text),
                    "stakeholder_id": stakeholder_id,
                    "source_span_id": span.id,
                    "status": "candidate",
                }
            )
            needs.append(
                {
                    "id": need_id,
                    "statement": span.text,
                    "stakeholder_id": stakeholder_id,
                    "concern_id": concern_id,
                    "source_span_id": span.id,
                    "status": "candidate",
                }
            )

    claims = []
    for claim in extracted_claims:
        value = asdict(claim)
        need_id = need_by_span.get(claim.span_id)
        value.update(
            source_type="need" if need_id else "constraint",
            need_id=need_id,
        )
        claims.append(value)

    present_roles = {item["name"] for item in stakeholders}
    checklist = tuple(
        question
        for role, question in (
            ("普通用户", "谁直接使用系统？"),
            ("管理员", "谁管理权限？"),
            ("运维人员", "谁维护部署与备份？"),
            ("数据负责人", "谁负责数据完整性？"),
            ("审计人员", "谁查看审计记录？"),
            ("项目负责人", "谁批准需求和变更？"),
            ("外部系统", "哪些外部系统与其交互？"),
        )
        if role not in present_roles
    )
    return {
        "artifact": asdict(artifact),
        "spans": [asdict(span) for span in spans],
        "stakeholders": sorted(stakeholders, key=lambda item: (item["name"], item["id"])),
        "concerns": sorted(concerns, key=lambda item: item["id"]),
        "needs": sorted(needs, key=lambda item: item["id"]),
        "claims": sorted(claims, key=lambda item: item["id"]),
        "scenarios": [],
        "scenario_runs": [],
        "checklist": checklist,
        "rflp": None,
        "coverage": {},
        "svg": "",
        "traceability": [],
        "draft": False,
        "draft_warnings": [],
    }


def empty_workbench() -> dict[str, object]:
    """Create a minimal local workbench for starting with a stakeholder."""
    digest = canonical_hash(("manual-workbench", "rflp-lite"))
    return {
        "artifact": {
            "id": f"artifact-{digest[:12]}",
            "kind": "manual",
            "path": "manual-input",
            "sha256": digest,
        },
        "spans": [],
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "claims": [],
        "scenarios": [],
        "scenario_runs": [],
        "checklist": [],
        "rflp": None,
        "coverage": {},
        "svg": "",
        "traceability": [],
        "draft": False,
        "draft_warnings": [],
        "baseline": None,
        "project": None,
    }


def merge_artifact(
    state: dict[str, object], filename: str, content: bytes
) -> dict[str, object]:
    """把另一份需求文档的候选并入现有工作台（按 id 去重），并作废旧模型输出。"""
    fresh = analyze_artifact(filename, content)
    result = _clone(state)
    result["artifact"] = fresh["artifact"]
    for group in ("spans", "stakeholders", "concerns", "needs", "claims"):
        existing_ids = {item["id"] for item in result[group]}
        result[group] = sorted(
            result[group]
            + [item for item in fresh[group] if item["id"] not in existing_ids],
            key=lambda item: item["id"],
        )
    result["checklist"] = fresh["checklist"]
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["baseline"], result["project"] = None, None
    result["draft"], result["draft_warnings"] = False, []
    return result


def add_stakeholder(state: dict[str, object], name: str) -> dict[str, object]:
    """Add a user-entered stakeholder without inventing related requirements."""
    clean_name = " ".join(name.split())
    if not clean_name:
        raise InvariantViolation("利益相关方名称不能为空")
    result = _clone(state)
    existing = next(
        (item for item in result["stakeholders"] if item["name"].casefold() == clean_name.casefold()),
        None,
    )
    if existing is not None:
        return result
    source_span_id = result["spans"][0]["id"] if result["spans"] else "manual"
    result["stakeholders"].append(
        {
            "id": _id("stkc", "manual", clean_name),
            "name": clean_name,
            "candidate_type": "manual",
            "source_span_id": source_span_id,
            "confidence": 1.0,
            "reason": "用户手动输入",
            "producer": "user",
            "status": "candidate",
        }
    )
    result["stakeholders"] = sorted(
        result["stakeholders"], key=lambda item: (item["name"], item["id"])
    )
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["baseline"], result["project"] = None, None
    result["draft"], result["draft_warnings"] = False, []
    return result


def stakeholder_bundle(state: dict[str, object], name: str = "") -> dict[str, object]:
    """Collect the traceable objects belonging to one stakeholder."""
    stakeholders = sorted(
        state.get("stakeholders", ()), key=lambda item: (item["name"], item["id"])
    )
    selected = next(
        (item for item in stakeholders if item["name"].casefold() == name.casefold()),
        None,
    )
    if selected is None and stakeholders:
        selected = stakeholders[0]
    if selected is None:
        return {
            "selected": None,
            "stakeholders": stakeholders,
            "concerns": (),
            "needs": (),
            "claims": (),
            "scenarios": (),
            "elements": (),
            "relations": (),
        }
    stakeholder_id = selected["id"]
    concerns = tuple(
        item for item in state.get("concerns", ()) if item.get("stakeholder_id") == stakeholder_id
    )
    needs = tuple(
        item for item in state.get("needs", ()) if item.get("stakeholder_id") == stakeholder_id
    )
    need_ids = {item["id"] for item in needs}
    claims = tuple(
        item
        for item in state.get("claims", ())
        if item.get("need_id") in need_ids
        or str(item.get("subject", "")).casefold() == selected["name"].casefold()
    )
    claim_ids = {item["id"] for item in claims}
    scenarios = tuple(
        item
        for item in state.get("scenarios", ())
        if selected["name"].casefold() in " ".join(item.get("actors", ())).casefold()
        or claim_ids.intersection(item.get("requirement_ids", ()))
    )
    elements: tuple[dict[str, object], ...] = ()
    relations: tuple[dict[str, object], ...] = ()
    rflp = state.get("rflp") or {}
    if rflp:
        requirement_ids = {
            item["id"]
            for item in rflp.get("elements", ())
            if item.get("layer") == "R"
            and any(
                key == "claim_id" and value in claim_ids
                for key, value in item.get("attributes", ())
            )
        }
        related_ids = set(requirement_ids)
        graph_relations = tuple(rflp.get("relations", ()))
        for _ in range(4):
            related_ids.update(
                relation["target_id"]
                for relation in graph_relations
                if relation["source_id"] in related_ids
            )
            related_ids.update(
                relation["source_id"]
                for relation in graph_relations
                if relation["target_id"] in related_ids
            )
        elements = tuple(
            item for item in rflp.get("elements", ()) if item["id"] in related_ids
        )
        relations = tuple(
            item
            for item in graph_relations
            if item["source_id"] in related_ids and item["target_id"] in related_ids
        )
    return {
        "selected": selected,
        "stakeholders": stakeholders,
        "concerns": concerns,
        "needs": needs,
        "claims": claims,
        "scenarios": scenarios,
        "elements": elements,
        "relations": relations,
    }


def review_item(
    state: dict[str, object],
    group: str,
    item_id: str,
    status: str,
    value: str = "",
) -> dict[str, object]:
    if group not in _GROUPS or status not in _STATUSES:
        raise InvariantViolation("invalid review action")
    result = _clone(state)
    items = result[group]
    item = next((candidate for candidate in items if candidate["id"] == item_id), None)
    if item is None:
        raise InvariantViolation("review item not found")
    field = {"stakeholders": "name", "concerns": "name", "needs": "statement", "claims": "object"}[group]
    if value.strip():
        item[field] = value.strip()
    item["status"] = status
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["baseline"], result["project"] = None, None
    return result


def accept_traceable(state: dict[str, object]) -> dict[str, object]:
    result = _clone(state)
    result["baseline"], result["project"] = None, None
    for stakeholder in result["stakeholders"]:
        if stakeholder["candidate_type"] in {"explicit", "manual"} and stakeholder["status"] == "candidate":
            stakeholder["status"] = "accepted"
    accepted_stakeholders = {
        item["id"] for item in result["stakeholders"] if item["status"] == "accepted"
    }
    for concern in result["concerns"]:
        if concern["stakeholder_id"] in accepted_stakeholders and concern["status"] == "candidate":
            concern["status"] = "accepted"
    accepted_concerns = {
        item["id"] for item in result["concerns"] if item["status"] == "accepted"
    }
    for need in result["needs"]:
        if (
            need["stakeholder_id"] in accepted_stakeholders
            and need["concern_id"] in accepted_concerns
            and need["status"] == "candidate"
        ):
            need["status"] = "accepted"
    accepted_needs = {item["id"] for item in result["needs"] if item["status"] == "accepted"}
    for claim in result["claims"]:
        if claim["status"] != "candidate":
            continue
        if claim["source_type"] == "constraint" or claim.get("need_id") in accepted_needs:
            claim["status"] = "accepted"
    return result


def _coverage(elements: tuple[ModelElement, ...], relations: tuple[Relation, ...]) -> dict[str, int]:
    ids_by_layer = {
        layer: {element.id for element in elements if element.layer == layer}
        for layer in "RFLP"
    }
    checks = (
        ("R-F", "R", "satisfiedBy", "source_id"),
        ("F-L", "F", "allocatedTo", "source_id"),
        ("L-P", "L", "realizedBy", "source_id"),
    )
    result = {}
    for label, layer, predicate, side in checks:
        covered = {getattr(relation, side) for relation in relations if relation.predicate == predicate}
        total = ids_by_layer[layer]
        result[label] = round(len(total & covered) * 100 / len(total)) if total else 0
    return result


def render_rflp_svg(
    elements: tuple[ModelElement, ...],
    relations: tuple[Relation, ...],
    stakeholders: tuple[str, ...] = (),
) -> str:
    layers = {
        layer: tuple(sorted((item for item in elements if item.layer == layer), key=lambda item: (item.name, item.id)))
        for layer in "RFLP"
    }
    max_items = max((len(items) for items in layers.values()), default=1)
    width, height = 1180, max(360, 180 + max_items * 86)
    positions: dict[str, tuple[int, int]] = {}
    parts = [
        f'<svg class="rflp-svg" viewBox="0 0 {width} {height}" role="img" aria-label="RFLP 规划图" xmlns="http://www.w3.org/2000/svg">',
        '<defs><marker id="rflp-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#607a73"/></marker></defs>',
        '<rect width="1180" height="100%" rx="16" fill="#0b1416"/>',
        '<text x="24" y="34" fill="#70e1bc" font-size="12" font-weight="700">STAKEHOLDER → NEED → REQUIREMENT → RFLP</text>',
        f'<text x="24" y="58" fill="#a9bbb6" font-size="13">来源：{escape(" · ".join(stakeholders) or "法规 / 系统约束")}</text>',
    ]
    for layer_index, layer in enumerate("RFLP"):
        x = 20 + layer_index * 290
        parts.extend(
            (
                f'<rect x="{x}" y="82" width="270" height="{height - 102}" rx="13" fill="#121f22" stroke="#263a3a"/>',
                f'<text x="{x + 16}" y="112" fill="#70e1bc" font-size="18" font-weight="800">{layer}</text>',
            )
        )
        for item_index, item in enumerate(layers[layer]):
            y = 130 + item_index * 86
            positions[item.id] = (x + 14, y)
            parts.extend(
                (
                    f'<rect x="{x + 14}" y="{y}" width="242" height="60" rx="9" fill="#182a2e" stroke="#31504b"/>',
                    f'<text x="{x + 26}" y="{y + 25}" fill="#e2eeea" font-size="12">{escape(item.name[:32])}</text>',
                    f'<text x="{x + 26}" y="{y + 44}" fill="#708b84" font-size="9">{escape(item.id)}</text>',
                )
            )
    for relation in sorted(relations, key=lambda item: item.id):
        if relation.source_id not in positions or relation.target_id not in positions:
            continue
        source_x, source_y = positions[relation.source_id]
        target_x, target_y = positions[relation.target_id]
        x1, y1 = source_x + 242, source_y + 30
        x2, y2 = target_x, target_y + 30
        middle = (x1 + x2) // 2
        parts.append(
            f'<path d="M{x1},{y1} C{middle},{y1} {middle},{y2} {x2},{y2}" fill="none" stroke="#607a73" stroke-width="1.5" marker-end="url(#rflp-arrow)"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def generate_model(state: dict[str, object]) -> dict[str, object]:
    result = _clone(state)
    result["baseline"], result["project"] = None, None
    accepted_stakeholders = {
        item["id"] for item in result["stakeholders"] if item["status"] == "accepted"
    }
    accepted_concerns = {
        item["id"] for item in result["concerns"] if item["status"] == "accepted"
    }
    accepted_needs = {
        item["id"]: item for item in result["needs"] if item["status"] == "accepted"
    }
    claims = []
    for item in result["claims"]:
        if item["status"] != "accepted":
            continue
        if item["source_type"] == "need":
            need = accepted_needs.get(item.get("need_id"))
            if (
                need is None
                or need["stakeholder_id"] not in accepted_stakeholders
                or need["concern_id"] not in accepted_concerns
            ):
                raise InvariantViolation("accepted requirement has incomplete stakeholder provenance")
        claims.append(
            Claim(
                id=item["id"],
                span_id=item["span_id"],
                subject=item["subject"],
                predicate=item["predicate"],
                object=item["object"],
                confidence=float(item["confidence"]),
                status="accepted",
            )
        )
    if not claims:
        raise InvariantViolation("请先接受至少一条可追溯需求")
    elements, relations = synthesize_rflp(tuple(claims))
    stakeholder_names = tuple(
        sorted(item["name"] for item in result["stakeholders"] if item["status"] == "accepted")
    )
    result["rflp"] = {
        "elements": [asdict(item) for item in elements],
        "relations": [asdict(item) for item in relations],
    }
    spans = {item["id"]: item for item in result["spans"]}
    stakeholders = {item["id"]: item for item in result["stakeholders"]}
    concerns = {item["id"]: item for item in result["concerns"]}
    result["traceability"] = []
    for item in result["claims"]:
        if item["status"] != "accepted":
            continue
        need = accepted_needs.get(item.get("need_id"))
        stakeholder = stakeholders.get(need["stakeholder_id"]) if need else None
        concern = concerns.get(need["concern_id"]) if need else None
        span = spans.get(item["span_id"])
        result["traceability"].append(
            {
                "requirement": item["object"],
                "stakeholder": stakeholder["name"] if stakeholder else "法规 / 系统约束",
                "concern": concern["name"] if concern else "约束完整性",
                "need": need["statement"] if need else item["object"],
                "source": span["locator"] if span else item["span_id"],
            }
        )
    result["coverage"] = _coverage(elements, relations)
    result["svg"] = render_rflp_svg(elements, relations, stakeholder_names)
    result["draft"] = False
    result["draft_warnings"] = []
    return result


def generate_draft_model(state: dict[str, object]) -> dict[str, object]:
    """Generate a viewable model without changing the review decisions.

    A draft is deliberately useful before formal review: it turns the rule
    claims that are already available into a graph, while keeping the source
    state as candidate data and clearly marking the output as provisional.
    """
    candidate_state = _clone(state)
    if not candidate_state["claims"]:
        # Keep the formal extractor conservative, but still make the minimum
        # viable path useful for plain-language notes that lack an obligation
        # keyword. These transient claims never become formal requirements.
        candidate_state["claims"] = [
            {
                "id": _id("draft-claim", span["id"]),
                "span_id": span["id"],
                "subject": "需求文档",
                "predicate": "待确认",
                "object": span["text"],
                "confidence": 0.35,
                "status": "accepted",
                "source_type": "constraint",
                "need_id": None,
            }
            for span in candidate_state["spans"]
        ]
    for group in _GROUPS:
        for item in candidate_state[group]:
            if item["status"] == "candidate":
                item["status"] = "accepted"
    generated = generate_model(candidate_state)
    result = _clone(state)
    for field in ("rflp", "coverage", "svg", "traceability"):
        result[field] = generated[field]
    result["baseline"], result["project"] = None, None
    result["draft"] = True
    result["draft_warnings"] = [
        "这是快速草稿图，尚未经过人工审核。",
        "确认需求后可生成正式模型并批准基线。",
    ]
    if not state["claims"]:
        result["draft_warnings"].insert(
            0, "原文没有明确的必须/应当等规则词，图中的节点均需人工确认。"
        )
    return result


def _json_content(text: str) -> object:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = "\n".join(stripped.splitlines()[1:-1])
        if stripped.lstrip().startswith("json"):
            stripped = stripped.lstrip()[4:].lstrip()
    return json.loads(stripped)


def add_llm_suggestions(
    state: dict[str, object], config: dict[str, object] | None = None
) -> dict[str, object]:
    if config is None:
        base_url = os.getenv("RFLP_LLM_BASE_URL", "").rstrip("/")
        model = os.getenv("RFLP_LLM_MODEL", "")
        api_key = os.getenv("RFLP_LLM_API_KEY", "")
        if not (base_url and model and api_key):
            raise AdapterFailure("LLM 未配置")
        config = {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "timeout_seconds": 20,
        }
    if not config.get("base_url") or not config.get("model"):
        raise AdapterFailure("LLM 未配置")
    if config.get("kind", "remote") == "remote" and not config.get("api_key"):
        raise AdapterFailure("当前远程 LLM 档案未配置 API Key，请到 LLM 设置保存并启用")
    result = _clone(state)
    spans = result["spans"]
    prompt = {
        "task": "从文本中提出隐含利益相关方候选。只返回 JSON 数组。",
        "schema": {
            "stakeholder": "string",
            "concern": "string",
            "need": "string",
            "source_span_id": "string",
        },
        "spans": spans,
    }
    try:
        content = chat_completion(
            config,
            [{"role": "user", "content": canonical_json(prompt)}],
        )
        suggestions = _json_content(content)
    except AdapterFailure as exc:
        raise AdapterFailure(f"LLM 分析失败: {exc}") from exc
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise AdapterFailure(f"LLM 分析失败: {type(exc).__name__}") from exc
    if not isinstance(suggestions, list):
        raise AdapterFailure("LLM 输出必须是 JSON 数组")
    span_ids = {item["id"] for item in spans}
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            raise AdapterFailure("LLM 候选格式无效")
        required = {"stakeholder", "concern", "need", "source_span_id"}
        if set(suggestion) != required or suggestion["source_span_id"] not in span_ids:
            raise AdapterFailure("LLM 候选缺少有效来源")
        stakeholder_id = _id("stkc", "llm", suggestion["stakeholder"], suggestion["source_span_id"])
        concern_id = _id("concern", stakeholder_id, suggestion["concern"])
        need_id = _id("need", stakeholder_id, suggestion["need"])
        result["stakeholders"].append(
            {
                "id": stakeholder_id,
                "name": str(suggestion["stakeholder"]),
                "candidate_type": "inferred",
                "source_span_id": suggestion["source_span_id"],
                "confidence": 0.5,
                "reason": "LLM 根据责任或关注点提出",
                "producer": "llm",
                "status": "candidate",
            }
        )
        result["concerns"].append(
            {
                "id": concern_id,
                "name": str(suggestion["concern"]),
                "stakeholder_id": stakeholder_id,
                "source_span_id": suggestion["source_span_id"],
                "status": "candidate",
            }
        )
        result["needs"].append(
            {
                "id": need_id,
                "statement": str(suggestion["need"]),
                "stakeholder_id": stakeholder_id,
                "concern_id": concern_id,
                "source_span_id": suggestion["source_span_id"],
                "status": "candidate",
            }
        )
    return result
