"""Deterministic customer-domain requirement extraction.

The extractor is intentionally conservative: it creates reviewable candidates
with source provenance and never marks a candidate as accepted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rflp_lite.application.resources import resource_path
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.requirements import DocumentRegion, StructuredRequirement


_PUNCTUATION = "。.!！?？;；"
_VERB_PATTERN = re.compile(
    r"^(?P<subject>.+?)(?P<predicate>必须|应当|不得|禁止|需要|支持|具备|能够|自动|生成|调用|推荐|应)(?P<object>.+)$"
)
_LEADING_VERB = re.compile(
    r"^(?P<predicate>支持|具备|能够|自动|生成|调用|推荐)(?P<object>.+)$"
)
_COUNT_RANGE = re.compile(r"(?P<low>\d+)\s*(?:~|～|至|-|—)\s*(?P<high>\d+)\s*(?P<unit>套|个|组|种)?")
_NUMBERED_METRIC = re.compile(
    r"(?P<operator>>=|<=|≥|≤|>|<|不少于|不超过|不得大于|不高于|不低于|至少|以上)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>km/h|m/s|kg|km|mm|m|s|秒|N|Pa|°|%|套)?",
    re.IGNORECASE,
)


def _load_glossary() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "resources" / "domain" / "ai4mbse-glossary.json"
    if not path.is_file():
        path = resource_path("src/rflp_lite/resources/domain/ai4mbse-glossary.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entities": [], "verbs": [], "units": []}


def _clean(text: str) -> str:
    return text.strip().strip(_PUNCTUATION).strip()


def _as_regions(document: Any) -> tuple[DocumentRegion, ...]:
    if hasattr(document, "regions"):
        return tuple(document.regions)
    if isinstance(document, dict):
        values = document.get("document_regions") or document.get("regions") or document.get("spans") or ()
    else:
        values = document
    regions: list[DocumentRegion] = []
    for index, value in enumerate(values, 1):
        if isinstance(value, DocumentRegion):
            regions.append(value)
            continue
        if isinstance(value, str):
            regions.append(
                DocumentRegion(
                    id=f"region-{index}",
                    artifact_id="",
                    page=1,
                    kind="paragraph",
                    locator=f"paragraph-{index}",
                    text=value,
                )
            )
            continue
        item = dict(value)
        regions.append(
            DocumentRegion(
                id=str(item.get("id") or f"region-{index}"),
                artifact_id=str(item.get("artifact_id", "")),
                page=item.get("page"),
                kind=str(item.get("kind", "paragraph")),
                locator=str(item.get("locator", f"paragraph-{index}")),
                text=str(item.get("text", "")),
                bbox=tuple(item.get("bbox", ())),
                confidence=float(item.get("confidence", 1.0)),
            )
        )
    return tuple(regions)


def _entities(text: str, glossary: dict[str, Any]) -> tuple[str, ...]:
    names = sorted((str(item) for item in glossary.get("entities", ())), key=len, reverse=True)
    return tuple(name for name in names if name.casefold() in text.casefold())


def _constraints(text: str) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    count = _COUNT_RANGE.search(text)
    if count:
        values.extend(
            (
                ("candidate_count_min", count.group("low")),
                ("candidate_count_max", count.group("high")),
            )
        )
        if count.group("unit"):
            values.append(("candidate_count_unit", count.group("unit")))
    for index, match in enumerate(_NUMBERED_METRIC.finditer(text), 1):
        values.append((f"candidate_metric_{index}", " ".join(part for part in (match.group("operator"), match.group("value"), match.group("unit")) if part)))
    return tuple(values)


def _parse(text: str) -> tuple[str, str, str]:
    clean = _clean(text)
    leading = _LEADING_VERB.match(clean)
    if leading:
        return "系统", leading.group("predicate"), _clean(leading.group("object"))
    matched = _VERB_PATTERN.match(clean)
    if matched:
        return _clean(matched.group("subject")) or "系统", matched.group("predicate"), _clean(matched.group("object"))
    return "系统", "描述", clean


def _verification_method(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("仿真", "降阶模型", "计算", "分析")):
        return "analysis"
    if any(word in lowered for word in ("检查", "审查", "标注", "公差")):
        return "inspection"
    if any(word in lowered for word in ("测试", "验证", "运行")):
        return "test"
    return "review"


def extract_requirement_candidates(document: Any) -> tuple[StructuredRequirement, ...]:
    glossary = _load_glossary()
    result: list[StructuredRequirement] = []
    for region in _as_regions(document):
        text = str(region.text).strip()
        if not text:
            continue
        subject, predicate, statement = _parse(text)
        entities = _entities(text, glossary)
        source_type = "provisional" if predicate == "描述" else "explicit"
        result.append(
            StructuredRequirement.from_fields(
                region=region,
                subject=subject,
                predicate=predicate,
                statement=statement,
                source_type=source_type,
                entities=entities,
                constraints=_constraints(text),
                verification_method=_verification_method(text),
                confidence=min(1.0, max(0.5, float(region.confidence))),
                producer="rule",
                rationale="客户原文中的能力、约束或目标描述",
            )
        )
    return tuple(sorted(result, key=lambda item: item.id))


def requirement_payload(candidate: StructuredRequirement, producer: str | None = None) -> dict[str, object]:
    """Return JSON-safe data and the explicit human-approval gate."""

    value = {
        "id": candidate.id,
        "source_region_id": candidate.source_region_id,
        "subject": candidate.subject,
        "predicate": candidate.predicate,
        "statement": candidate.statement,
        "object": candidate.statement,
        "source_type": candidate.source_type,
        "entities": list(candidate.entities),
        "constraints": [[key, item] for key, item in candidate.constraints],
        "verification_method": candidate.verification_method,
        "verification_metric": candidate.verification_metric,
        "priority": candidate.priority,
        "rationale": candidate.rationale,
        "confidence": candidate.confidence,
        "status": candidate.status,
        "producer": producer or candidate.producer,
    }
    value["bulk_approvable"] = value["source_type"] in {"explicit", "user"} and value["producer"] != "llm"
    return value


def entity_payloads(document: Any) -> tuple[dict[str, object], ...]:
    glossary = _load_glossary()
    records: dict[str, dict[str, object]] = {}
    for region in _as_regions(document):
        for name in _entities(region.text, glossary):
            record = records.setdefault(
                name.casefold(),
                {
                    "id": f"entity-{canonical_hash((name,))[:12]}",
                    "name": name,
                    "kind": "domain_entity",
                    "source_region_ids": [],
                    "confidence": 1.0,
                    "status": "candidate",
                },
            )
            record["source_region_ids"].append(region.id)
    return tuple(sorted(records.values(), key=lambda item: item["id"]))
