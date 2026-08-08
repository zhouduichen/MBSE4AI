from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from html import escape

from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.adapters.readers import RuleClaimExtractor, read_artifact
from rflp_lite.adapters.llm_client import chat_completion
from rflp_lite.application.synthesize import synthesize_rflp
from rflp_lite.application.requirement_semantics import (
    entity_payloads,
    extract_requirement_candidates,
    requirement_payload,
)
from rflp_lite.application.requirement_inference import inferred_requirement_payloads
from rflp_lite.application.traceability import refresh_traceability
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import AdapterFailure, InvariantViolation
from rflp_lite.domain.models import Claim, ModelElement, Relation, TextSpan
from rflp_lite.domain.requirements import DocumentRegion


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
_STAKEHOLDER_CATEGORY_ALIASES = {
    "customer": ("客户", "甲方", "业主", "产品负责人", "项目负责人", "车主"),
    "end_user": ("普通用户", "最终用户", "用户", "驾驶员", "乘员", "乘客"),
    "operator": ("管理员", "操作员", "运维人员", "运维", "维护人员", "调度员", "内容管理员", "内容编辑人员"),
    "engineering": ("系统工程师", "系统架构师", "研发人员", "开发人员", "设计人员", "工程师"),
    "supplier": ("供应商", "制造商", "生产人员", "零部件供应商"),
    "regulator": ("监管机构", "监管方", "监管人员", "审计人员", "审核员", "认证机构", "标准组织"),
    "external_system": ("外部系统", "第三方平台", "接口系统", "合作系统"),
    "environment": ("环境", "自然环境", "法规", "约束条件"),
}
_GROUPS = {"stakeholders", "concerns", "needs", "claims", "structured_requirements"}
_STATUSES = {"candidate", "accepted", "rejected"}
STAKEHOLDER_CATEGORIES = (
    ("customer", "客户 / 系统拥有者"),
    ("end_user", "最终用户"),
    ("operator", "操作 / 运维"),
    ("engineering", "系统工程 / 研发"),
    ("supplier", "制造 / 供应商"),
    ("regulator", "监管 / 标准 / 审计"),
    ("external_system", "外部系统"),
    ("environment", "环境 / 约束"),
    ("other", "其他"),
)
_STAKEHOLDER_CATEGORY_KEYS = {key for key, _ in STAKEHOLDER_CATEGORIES}
_STAKEHOLDER_CATEGORY_LABELS = dict(STAKEHOLDER_CATEGORIES)
_SYSTEM_INTENT = re.compile(
    r"^(?:设置|建立|创建|构建|设计|开发|建设|规划|做|我想要|希望|期望|想做)"
    r"(?:一个|一套|一款)?\s*(?P<name>.+)$"
)
_QUALITY_ATTRIBUTES = (
    "鲁棒性",
    "可靠性",
    "可用性",
    "安全性",
    "性能",
    "低延迟",
    "可扩展性",
    "可维护性",
    "易用性",
    "兼容性",
    "准确性",
    "实时性",
    "容错性",
    "稳定性",
)
_QUALITY_PATTERN = re.compile(
    r"(?P<value>(?:极高|极低|高|低|强|弱)?(?:"
    + "|".join(re.escape(item) for item in _QUALITY_ATTRIBUTES)
    + r"))"
)


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


def stakeholder_category(name: str) -> str:
    """Return a stable category key for a stakeholder role."""
    clean_name = str(name or "").strip().casefold()
    for category, aliases in _STAKEHOLDER_CATEGORY_ALIASES.items():
        if any(alias.casefold() in clean_name for alias in aliases):
            return category
    return "other"


def stakeholder_category_label(category: str) -> str:
    return _STAKEHOLDER_CATEGORY_LABELS.get(
        str(category), _STAKEHOLDER_CATEGORY_LABELS["other"]
    )


def normalize_stakeholder_category(category: str, name: str = "") -> str:
    clean = str(category or "").strip()
    return clean if clean in _STAKEHOLDER_CATEGORY_KEYS else stakeholder_category(name)


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


def _system_context(spans: tuple[object, ...], has_formal_claims: bool) -> dict[str, object]:
    source = str(getattr(spans[0], "text", "")).strip() if spans else ""
    candidate = ""
    match = _SYSTEM_INTENT.match(source.rstrip("。.!！?？"))
    if match:
        candidate = match.group("name").strip(" 。.!！?？")
    if not candidate and any(word in source for word in ("航天", "卫星", "火箭", "空间")):
        candidate = next(
            (word for word in ("航天系统", "卫星系统", "火箭系统", "空间系统") if word in source),
            "航天系统",
        )
    if not candidate or len(candidate) > 48:
        candidate = "待命名系统"
    domain = next(
        (
            name
            for words, name in (
                (("航天", "卫星", "火箭", "空间", "飞控", "载荷"), "航天"),
                (("医疗", "医院", "患者", "诊疗"), "医疗"),
                (("制造", "工厂", "产线", "设备"), "制造"),
                (("金融", "支付", "银行", "账户"), "金融"),
            )
            if any(word in source.casefold() for word in words)
        ),
        "通用",
    )
    return {
        "name": candidate,
        "domain": domain,
        "source_text": source,
        "source_span_id": getattr(spans[0], "id", ""),
        "status": "formal-candidate" if has_formal_claims else "draft",
        "confidence": 0.9 if candidate != "待命名系统" else 0.35,
        "next_actions": ("补充系统目标", "补充核心功能", "补充接口与约束"),
    }


def _quality_claim(span: object, system_context: dict[str, object]) -> dict[str, object] | None:
    text = str(getattr(span, "text", "")).strip().rstrip("。.!！?？")
    match = _QUALITY_PATTERN.search(text)
    if match is None:
        return None
    attribute = match.group("value")
    subject = "系统" if "系统" in text else str(system_context["name"])
    return {
        "id": _id("quality-claim", getattr(span, "id", ""), attribute),
        "span_id": getattr(span, "id", ""),
        "subject": subject,
        "predicate": "应具备",
        "object": attribute if attribute in text else text,
        "confidence": 0.78,
        "status": "candidate",
        "source_type": "constraint",
        "candidate_type": "quality-attribute",
        "interpretation": "质量属性候选",
        "need_id": None,
    }


def _free_form_claim(span: object, system_context: dict[str, object]) -> dict[str, object]:
    text = str(getattr(span, "text", "")).strip()
    lowered = text.casefold()
    if any(word in lowered for word in ("无法", "不能", "经常", "失败", "问题", "痛点", "担心")):
        candidate_type, predicate, interpretation = "problem", "待解决", "问题或痛点候选"
    elif any(word in lowered for word in ("希望", "想要", "设置", "建立", "创建", "做一个", "支持", "提供")):
        candidate_type, predicate, interpretation = "goal", "系统目标", "目标或能力候选"
    else:
        candidate_type, predicate, interpretation = "provisional", "待确认", "待分类候选"
    return {
        "id": _id("draft-claim", getattr(span, "id", "")),
        "span_id": getattr(span, "id", ""),
        "subject": system_context["name"],
        "predicate": predicate,
        "object": text,
        "confidence": 0.35,
        "status": "candidate",
        "source_type": candidate_type,
        "candidate_type": candidate_type,
        "interpretation": interpretation,
        "need_id": None,
    }


def analyze_artifact(filename: str, content: bytes) -> dict[str, object]:
    # Keep the original reader for source-code and structured data while the
    # document parser provides page-aware regions for customer documents.
    if os.path.splitext(filename)[1].lower() in {".txt", ".md", ".markdown", ".docx", ".pdf"}:
        parsed = LocalDocumentParser().parse(filename, content)
        artifact = parsed.artifact
        spans = tuple(
            TextSpan(region.id.replace("region-", "span-", 1), region.artifact_id, region.locator, region.text)
            for region in parsed.regions
        )
        document_pages = [
            {"number": page.number, "width": page.width, "height": page.height}
            for page in parsed.pages
        ]
        document_regions = [asdict(region) for region in parsed.regions]
        diagnostics = [asdict(item) for item in parsed.diagnostics]
    else:
        artifact, spans = read_artifact(filename, content)
        document_pages = [{"number": 1, "width": None, "height": None}]
        document_regions = [
            {
                "id": span.id.replace("span-", "region-", 1),
                "artifact_id": span.artifact_id,
                "page": 1,
                "kind": "text",
                "locator": span.locator,
                "text": span.text,
                "bbox": [],
                "confidence": 1.0,
            }
            for span in spans
        ]
        diagnostics = []
    extracted_claims = RuleClaimExtractor().extract(spans)
    structured_candidates = extract_requirement_candidates(
        {"document_regions": document_regions}
    )
    system_context = _system_context(spans, bool(extracted_claims))
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
                    "category": stakeholder_category(role),
                    "category_label": stakeholder_category_label(stakeholder_category(role)),
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
    structured_requirements = [requirement_payload(item) for item in structured_candidates]
    claims_by_span = {item.get("span_id"): item for item in claims}
    for item in structured_requirements:
        claim = claims_by_span.get(item["source_region_id"].replace("region-", "span-", 1))
        if claim is not None:
            claim["structured_requirement_id"] = item["id"]
            claim["producer"] = "rule"
            claim["bulk_approvable"] = item["bulk_approvable"]
        elif extracted_claims:
            claims.append(
                {
                    "id": _id("claim", item["id"]),
                    "span_id": item["source_region_id"].replace("region-", "span-", 1),
                    "subject": item["subject"],
                    "predicate": item["predicate"],
                    "object": item["statement"],
                    "confidence": item["confidence"],
                    "status": item["status"],
                    "source_type": "constraint" if item["constraints"] else "need",
                    "candidate_type": "explicit",
                    "interpretation": "结构化需求候选",
                    "need_id": None,
                    "structured_requirement_id": item["id"],
                    "producer": "rule",
                    "bulk_approvable": item["bulk_approvable"],
                }
            )
    extracted_span_ids = {claim.span_id for claim in extracted_claims}
    for span in spans:
        if span.id in extracted_span_ids:
            continue
        quality_claim = _quality_claim(span, system_context)
        if quality_claim is not None:
            claims.append(quality_claim)
    if not claims:
        for span in spans:
            claims.append(
                {
                    **_free_form_claim(span, system_context),
                    "need_id": need_by_span.get(span.id),
                }
            )

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
    result = {
        "schema_version": 2,
        "artifact": asdict(artifact),
        "system_context": system_context,
        "spans": [asdict(span) for span in spans],
        "document_pages": document_pages,
        "document_regions": document_regions,
        "entities": entity_payloads({"document_regions": document_regions}),
        "structured_requirements": structured_requirements,
        "trace_links": [],
        "diagnostics": diagnostics,
        "mbse": None,
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
        "draft_graph": None,
        "traceability": [],
        "draft": False,
        "draft_warnings": [],
        "flow": None,
    }
    return refresh_traceability(result)


def empty_workbench() -> dict[str, object]:
    """Create a minimal local workbench for starting with a stakeholder."""
    digest = canonical_hash(("manual-workbench", "rflp-lite"))
    return {
        "schema_version": 2,
        "artifact": {
            "id": f"artifact-{digest[:12]}",
            "kind": "manual",
            "path": "manual-input",
            "sha256": digest,
        },
        "system_context": None,
        "spans": [],
        "document_pages": [],
        "document_regions": [],
        "entities": [],
        "structured_requirements": [],
        "trace_links": [],
        "diagnostics": [],
        "mbse": None,
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
        "draft_graph": None,
        "traceability": [],
        "draft": False,
        "draft_warnings": [],
        "flow": None,
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
    result["system_context"] = fresh["system_context"]
    for group in ("spans", "stakeholders", "concerns", "needs", "claims", "structured_requirements", "entities"):
        existing_ids = {item["id"] for item in result[group]}
        result[group] = sorted(
            result[group]
            + [item for item in fresh[group] if item["id"] not in existing_ids],
            key=lambda item: item["id"],
        )
    result["document_regions"] = result.get("document_regions", []) + [
        item for item in fresh.get("document_regions", ())
        if item.get("id") not in {value.get("id") for value in result.get("document_regions", ())}
    ]
    result["document_pages"] = list(result.get("document_pages", ())) + list(fresh.get("document_pages", ()))
    result["diagnostics"] = list(result.get("diagnostics", ())) + list(fresh.get("diagnostics", ()))
    result["checklist"] = fresh["checklist"]
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["draft_graph"] = None
    result["baseline"], result["project"] = None, None
    result["draft"], result["draft_warnings"] = False, []
    result["flow"] = None
    return refresh_traceability(result)


def suggest_implicit_constraints(
    state: dict[str, object],
    config: dict[str, object],
    complete: object = None,
) -> dict[str, object]:
    """Append LLM-generated implicit constraints as individually reviewable candidates."""

    result = _clone(state)
    regions = tuple(
        DocumentRegion(
            id=str(item.get("id", "")),
            artifact_id=str(item.get("artifact_id", "")),
            page=item.get("page"),
            kind=str(item.get("kind", "paragraph")),
            locator=str(item.get("locator", "")),
            text=str(item.get("text", "")),
            bbox=tuple(item.get("bbox", ())),
            confidence=float(item.get("confidence", 1.0)),
        )
        for item in result.get("document_regions", ())
    )
    values = inferred_requirement_payloads(regions, config, complete)  # type: ignore[arg-type]
    existing = {item.get("id") for item in result.get("structured_requirements", ())}
    result.setdefault("structured_requirements", [])
    result["structured_requirements"].extend(
        item for item in values if item.get("id") not in existing
    )
    result["structured_requirements"] = sorted(
        result["structured_requirements"], key=lambda item: item.get("id", "")
    )
    result["diagnostics"] = [
        item for item in result.get("diagnostics", ())
        if item.get("code") != "implicit-requirements-suggested"
    ]
    result["diagnostics"].append(
        {
            "id": _id("diagnostic", "implicit-requirements-suggested", len(values)),
            "scope": "structured_requirements",
            "code": "implicit-requirements-suggested",
            "message": f"已生成 {len(values)} 条隐含约束候选，需逐条人工确认",
            "source_id": "",
            "severity": "info",
        }
    )
    return result


def add_stakeholder(
    state: dict[str, object], name: str, category: str = ""
) -> dict[str, object]:
    """Add a user-entered stakeholder without inventing related requirements."""
    clean_name = " ".join(name.split())
    if not clean_name:
        raise InvariantViolation("利益相关方名称不能为空")
    normalized_category = normalize_stakeholder_category(category, clean_name)
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
            "category": normalized_category,
            "category_label": stakeholder_category_label(normalized_category),
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
    result["draft_graph"] = None
    result["baseline"], result["project"] = None, None
    result["flow"] = None
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
    category: str = "",
) -> dict[str, object]:
    if group not in _GROUPS or status not in _STATUSES:
        raise InvariantViolation("invalid review action")
    result = _clone(state)
    items = result[group]
    item = next((candidate for candidate in items if candidate["id"] == item_id), None)
    if item is None:
        raise InvariantViolation("review item not found")
    field = {"stakeholders": "name", "concerns": "name", "needs": "statement", "claims": "object", "structured_requirements": "statement"}[group]
    if value.strip():
        item[field] = value.strip()
    if group == "stakeholders":
        normalized_category = normalize_stakeholder_category(
            category, str(item.get("name", ""))
        )
        item["category"] = normalized_category
        item["category_label"] = stakeholder_category_label(normalized_category)
    item["status"] = status
    result["rflp"], result["coverage"], result["svg"] = None, {}, ""
    result["draft_graph"] = None
    result["baseline"], result["project"] = None, None
    result["flow"] = None
    return result


def accept_traceable(state: dict[str, object]) -> dict[str, object]:
    result = _clone(state)
    result["baseline"], result["project"] = None, None
    result["flow"] = None
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
    for requirement in result.get("structured_requirements", ()):
        if requirement.get("status") == "candidate" and requirement.get("bulk_approvable", requirement.get("source_type") != "inferred"):
            requirement["status"] = "accepted"
    return result


def confirm_requirements(state: dict[str, object]) -> dict[str, object]:
    """Confirm the current interpretation after an explicit UI decision."""
    result = accept_traceable(state)
    for claim in result["claims"]:
        if claim["status"] == "candidate" and claim.get("source_type") != "need":
            claim["status"] = "accepted"
    for requirement in result.get("structured_requirements", ()):
        if requirement.get("status") == "candidate" and requirement.get("source_type") != "inferred" and requirement.get("producer") != "llm":
            requirement["status"] = "accepted"
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
    system_name: str = "",
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
        f'<text x="24" y="58" fill="#a9bbb6" font-size="13">系统：{escape(system_name or "待命名系统")} · 来源：{escape(" · ".join(stakeholders) or "法规 / 系统约束")}</text>',
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


def _draft_graph(state: dict[str, object]) -> dict[str, object]:
    context = state.get("system_context") or {}
    claims = list(state.get("claims", ()))
    items = []
    for claim in claims:
        source_type = str(claim.get("source_type", "provisional"))
        kind = {
            "goal": "目标 / 意图",
            "problem": "问题 / 风险",
            "constraint": "质量 / 约束",
            "need": "利益相关方需要",
        }.get(source_type, "待确认内容")
        items.append(
            {
                "id": str(claim.get("id", "")),
                "kind": kind,
                "text": str(claim.get("object", "")),
                "status": str(claim.get("status", "candidate")),
                "source_type": source_type,
            }
        )
    if not items:
        items = [
            {
                "id": str(span.get("id", "")),
                "kind": "原始输入",
                "text": str(span.get("text", "")),
                "status": "candidate",
                "source_type": "provisional",
            }
            for span in state.get("spans", ())
        ]
    return {
        "type": "understanding-map",
        "title": "需求理解图",
        "system": str(context.get("name") or "待命名系统"),
        "domain": str(context.get("domain") or "通用"),
        "source_text": str(context.get("source_text") or ""),
        "items": items,
        "open_questions": tuple(context.get("next_actions", ()))
        + ("哪些内容必须成为正式 Requirement？", "如何验证这些目标？"),
    }


def render_draft_svg(state: dict[str, object]) -> str:
    """Render a user-facing interpretation map, not a fake RFLP model."""
    graph = _draft_graph(state)
    items = tuple(graph["items"][:6])
    questions = tuple(dict.fromkeys(graph["open_questions"]))[:5]
    width = 1180
    height = max(520, 300 + max(len(items), len(questions)) * 58)
    parts = [
        f'<svg class="draft-understanding-svg" viewBox="0 0 {width} {height}" role="img" aria-label="需求理解图" xmlns="http://www.w3.org/2000/svg">',
        '<rect width="1180" height="100%" rx="16" fill="#171411"/>',
        '<text x="24" y="34" fill="#f0bd72" font-size="12" font-weight="800">需求理解图 · DRAFT</text>',
        '<text x="24" y="58" fill="#d4c4ae" font-size="13">这是对输入的当前理解，不是正式 RFLP，也不能作为项目基线。</text>',
    ]
    columns = ((20, 290, "系统主题"), (330, 430, "已理解内容"), (780, 380, "还需要确认"))
    for x, width_column, title in columns:
        parts.extend(
            (
                f'<rect x="{x}" y="86" width="{width_column}" height="{height - 122}" rx="13" fill="#211d18" stroke="#5d4830"/>',
                f'<text x="{x + 16}" y="116" fill="#f0bd72" font-size="16" font-weight="800">{escape(title)}</text>',
            )
        )
    parts.extend(
        (
            f'<text x="36" y="165" fill="#f5eee4" font-size="22" font-weight="800">{escape(graph["system"])}</text>',
            f'<text x="36" y="193" fill="#b9a78e" font-size="12">领域：{escape(graph["domain"])}</text>',
            f'<text x="36" y="235" fill="#d4c4ae" font-size="11">输入原文</text>',
            f'<text x="36" y="262" fill="#a8957d" font-size="11">{escape(graph["source_text"][:42])}</text>',
            '<text x="36" y="315" fill="#8d7b65" font-size="10">状态：草稿理解</text>',
        )
    )
    for index, item in enumerate(items):
        y = 145 + index * 58
        parts.extend(
            (
                f'<rect x="346" y="{y}" width="398" height="42" rx="8" fill="#2a241d" stroke="#9a7139" stroke-dasharray="5 4"/>',
                f'<text x="360" y="{y + 17}" fill="#f0bd72" font-size="9">{escape(str(item["kind"]))}</text>',
                f'<text x="360" y="{y + 33}" fill="#f5eee4" font-size="11">{escape(str(item["text"])[:46])}</text>',
            )
        )
    for index, question in enumerate(questions):
        y = 145 + index * 58
        parts.extend(
            (
                f'<rect x="796" y="{y}" width="348" height="42" rx="8" fill="#25201a" stroke="#6b5435"/>',
                f'<text x="812" y="{y + 25}" fill="#d4c4ae" font-size="11">{escape(str(question)[:45])}</text>',
            )
        )
    parts.append(
        f'<text x="24" y="{height - 20}" fill="#9b8058" font-size="10">下一步：确认或修改“已理解内容”，确认后才生成正式 RFLP。</text>'
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
    result["svg"] = render_rflp_svg(
        elements,
        relations,
        stakeholder_names,
        str((result.get("system_context") or {}).get("name", "")),
    )
    result["draft"] = False
    result["draft_graph"] = None
    result["draft_warnings"] = []
    result["flow"] = None
    return result


def generate_draft_model(state: dict[str, object]) -> dict[str, object]:
    """Generate a visible interpretation map without inventing formal RFLP."""
    result = _clone(state)
    result["rflp"] = None
    result["coverage"] = {}
    result["traceability"] = []
    result["draft_graph"] = _draft_graph(result)
    result["svg"] = render_draft_svg(result)
    result["baseline"], result["project"] = None, None
    result["draft"] = True
    result["flow"] = None
    result["draft_warnings"] = [
        "这是需求理解图，不是正式 RFLP。",
        "图中的内容仍是候选，确认后才会生成 R/F/L/P 正式模型。",
    ]
    if not any(item.get("source_type") in {"constraint", "need"} for item in state["claims"]):
        result["draft_warnings"].insert(
            0, "原文没有明确的必须/应当等规则词；输入已保留为目标、问题或质量属性候选，图中的节点仍需人工确认和补充验证指标。"
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
    existing_stakeholder_ids = {item["id"] for item in result["stakeholders"]}
    existing_concern_ids = {item["id"] for item in result["concerns"]}
    existing_need_ids = {item["id"] for item in result["needs"]}
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            raise AdapterFailure("LLM 候选格式无效")
        required = {"stakeholder", "concern", "need", "source_span_id"}
        if set(suggestion) != required or suggestion["source_span_id"] not in span_ids:
            raise AdapterFailure("LLM 候选缺少有效来源")
        stakeholder_id = _id("stkc", "llm", suggestion["stakeholder"], suggestion["source_span_id"])
        concern_id = _id("concern", stakeholder_id, suggestion["concern"])
        need_id = _id("need", stakeholder_id, suggestion["need"])
        if stakeholder_id not in existing_stakeholder_ids:
            inferred_category = stakeholder_category(str(suggestion["stakeholder"]))
            result["stakeholders"].append(
                {
                    "id": stakeholder_id,
                    "name": str(suggestion["stakeholder"]),
                    "category": inferred_category,
                    "category_label": stakeholder_category_label(inferred_category),
                    "candidate_type": "inferred",
                    "source_span_id": suggestion["source_span_id"],
                    "confidence": 0.5,
                    "reason": "LLM 根据责任或关注点提出",
                    "producer": "llm",
                    "status": "candidate",
                }
            )
            existing_stakeholder_ids.add(stakeholder_id)
        if concern_id not in existing_concern_ids:
            result["concerns"].append(
                {
                    "id": concern_id,
                    "name": str(suggestion["concern"]),
                    "stakeholder_id": stakeholder_id,
                    "source_span_id": suggestion["source_span_id"],
                    "status": "candidate",
                }
            )
            existing_concern_ids.add(concern_id)
        if need_id not in existing_need_ids:
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
            existing_need_ids.add(need_id)
    return result
