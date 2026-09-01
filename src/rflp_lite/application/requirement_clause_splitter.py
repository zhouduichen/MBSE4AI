"""Deterministic sentence-clause splitting for concept-design intake."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from rflp_lite.application.requirement_details import extract_explicit_details
from rflp_lite.application.requirement_semantics import (
    extract_requirement_candidates,
    requirement_payload,
)
from rflp_lite.domain.canonical import canonical_hash, to_primitive
from rflp_lite.domain.requirements import DocumentRegion


_SEPARATOR = re.compile(r"(?<!\d)[，,；;。.!！？?]+(?!\d)")
_NUMBER = r"\d+(?:\.\d+)?"
_UNIT = r"km/h|kg|km|m|s|千克|公斤|公里|米|秒"
_OPERATOR = r"不得大于|不得超过|不超过|不高于|不低于|不少于|至少|以上|<=|>=|≤|≥|<|>"
_METRIC = re.compile(
    rf"(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 _/\-]{{1,30}}?)"
    rf"\s*(?P<operator>{_OPERATOR})\s*"
    rf"(?P<value>{_NUMBER})\s*(?P<unit>{_UNIT})?",
    re.IGNORECASE,
)
_BARE_DURATION = re.compile(
    rf"(?P<name>通信中断|通信失联|失联|中断)\s*"
    rf"(?P<value>{_NUMBER})\s*(?P<unit>秒|s)",
    re.IGNORECASE,
)

_OPERATOR_ALIASES = {
    "不得大于": "<=",
    "不得超过": "<=",
    "不超过": "<=",
    "不高于": "<=",
    "≤": "<=",
    "<=": "<=",
    "不低于": ">=",
    "不少于": ">=",
    "至少": ">=",
    "以上": ">=",
    "≥": ">=",
    ">=": ">=",
    "<": "<",
    ">": ">",
}
_UNIT_ALIASES = {"千克": "kg", "公斤": "kg", "公里": "km", "米": "m", "秒": "s"}
_TRAILING_MODAL = re.compile(r"(?:应当|必须|应|需|要)$")


@dataclass(frozen=True, slots=True)
class NormalizedMetric:
    name: str
    value: float
    unit: str
    operator: str
    source_text: str


@dataclass(frozen=True, slots=True)
class RequirementClause:
    id: str
    source_region_id: str
    ordinal: int
    text: str
    kind: str
    normalized_metrics: tuple[NormalizedMetric, ...]


@dataclass(frozen=True, slots=True)
class ClauseAnalysis:
    clauses: tuple[RequirementClause, ...]
    requirements: tuple[dict[str, object], ...]
    attributes: tuple[dict[str, object], ...]
    constraints: tuple[dict[str, object], ...]


def _regions(value: str | Sequence[DocumentRegion]) -> tuple[DocumentRegion, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (
            DocumentRegion(
                id="region-1",
                artifact_id="",
                page=1,
                kind="paragraph",
                locator="paragraph-1",
                text=text,
            ),
        ) if text else ()
    return tuple(item for item in value if isinstance(item, DocumentRegion) and item.text.strip())


def _clean_name(value: str) -> str:
    name = re.sub(r"^[\s：:、，,]+|[\s：:、，,]+$", "", value)
    return _TRAILING_MODAL.sub("", name).strip() or name.strip()


def _metric_from_match(match: re.Match[str], *, operator: str | None = None) -> NormalizedMetric:
    raw_unit = (match.group("unit") or "").strip()
    return NormalizedMetric(
        name=_clean_name(match.group("name")),
        value=float(match.group("value")),
        unit=_UNIT_ALIASES.get(raw_unit, raw_unit),
        operator=operator or _OPERATOR_ALIASES[match.group("operator")],
        source_text=match.group(0).strip(),
    )


def _metrics(text: str) -> tuple[NormalizedMetric, ...]:
    values: list[NormalizedMetric] = []
    for match in _METRIC.finditer(text):
        values.append(_metric_from_match(match))
    for match in _BARE_DURATION.finditer(text):
        values.append(_metric_from_match(match, operator="=="))
    return tuple(values)


def _kind(text: str, metrics: tuple[NormalizedMetric, ...]) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("中断", "失联", "故障", "返航", "恢复", "自动")):
        return "behavior"
    if metrics:
        return "metric"
    if any(word in text for word in ("设计", "任务", "侦察", "系统", "平台")):
        return "mission"
    return "context"


class RequirementClauseSplitter:
    """Split source regions without changing source text or provenance."""

    def split(self, value: str | Sequence[DocumentRegion]) -> tuple[RequirementClause, ...]:
        clauses: list[RequirementClause] = []
        ordinal = 0
        for region in _regions(value):
            parts = [part.strip() for part in _SEPARATOR.split(region.text) if part.strip()]
            if not parts:
                parts = [region.text.strip()]
            for part in parts:
                ordinal += 1
                metrics = _metrics(part)
                identity = (region.id, ordinal, part, tuple(to_primitive(item) for item in metrics))
                clauses.append(
                    RequirementClause(
                        id=f"clause-{canonical_hash(identity)[:12]}",
                        source_region_id=region.id,
                        ordinal=ordinal,
                        text=part,
                        kind=_kind(part, metrics),
                        normalized_metrics=metrics,
                    )
                )
        return tuple(clauses)

    def analyze(self, value: str | Sequence[DocumentRegion]) -> ClauseAnalysis:
        clauses = self.split(value)
        temporary_regions = tuple(
            DocumentRegion(
                id=clause.id,
                artifact_id="",
                page=1,
                kind="paragraph",
                locator=f"clause-{clause.ordinal}",
                text=clause.text,
            )
            for clause in clauses
        )
        candidates = extract_requirement_candidates(temporary_regions)
        source_by_requirement = {
            candidate.id: next(
                clause.source_region_id for clause in clauses if clause.id == candidate.source_region_id
            )
            for candidate in candidates
        }
        requirements: list[dict[str, object]] = []
        for candidate in candidates:
            payload = requirement_payload(candidate)
            source_region_id = source_by_requirement[candidate.id]
            clause = next(item for item in clauses if item.id == candidate.source_region_id)
            payload.update(
                {
                    "source_region_id": source_region_id,
                    "source_region_ids": [source_region_id],
                    "source_clause_id": clause.id,
                    "normalized_metrics": [to_primitive(item) for item in clause.normalized_metrics],
                }
            )
            requirements.append(payload)

        detail_requirements = [
            {
                **item,
                "source_region_id": item["source_clause_id"],
                "source_region_ids": [item["source_clause_id"]],
            }
            for item in requirements
        ]
        temporary_text = {clause.id: clause.text for clause in clauses}
        attributes, constraints = extract_explicit_details(detail_requirements, temporary_text)
        source_by_clause = {clause.id: clause.source_region_id for clause in clauses}
        attribute_payloads = []
        for item in attributes:
            payload = to_primitive(item)
            payload["source_region_ids"] = [
                source_by_clause.get(str(source), str(source))
                for source in payload.get("source_region_ids", ())
            ]
            attribute_payloads.append(payload)
        constraint_payloads = []
        for item in constraints:
            payload = to_primitive(item)
            payload["source_region_ids"] = [
                source_by_clause.get(str(source), str(source))
                for source in payload.get("source_region_ids", ())
            ]
            constraint_payloads.append(payload)
        return ClauseAnalysis(
            clauses=clauses,
            requirements=tuple(sorted(requirements, key=lambda item: str(item["source_clause_id"]))),
            attributes=tuple(attribute_payloads),
            constraints=tuple(constraint_payloads),
        )


__all__ = [
    "ClauseAnalysis",
    "NormalizedMetric",
    "RequirementClause",
    "RequirementClauseSplitter",
]
