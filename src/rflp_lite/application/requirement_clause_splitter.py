"""Deterministic splitting and normalization for one-shot requirement input.

The splitter is deliberately rule-first.  It keeps the original clause text
and source region while making numeric constraints usable by downstream
application services.  Model-assisted enrichment, when enabled elsewhere,
can add semantics but must not replace these values.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rflp_lite.application.requirement_semantics import extract_requirement_candidates
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.requirement_details import RequirementAttribute, RequirementConstraint
from rflp_lite.domain.requirements import DocumentRegion, StructuredRequirement


_OPERATOR_PATTERN = r"不超过|不得大于|不高于|不大于|不低于|不少于|至少|以上|大于等于|小于等于|等于|≤|≥|<=|>=|==|<|>"
_UNIT_PATTERN = r"km/h|m/s|kg|km|mm|m2|m3|Pa|m|s|秒|米|千克"
_METRIC_PATTERN = re.compile(
    rf"(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 _/\-]{{1,32}}?)"
    rf"\s*(?P<operator>{_OPERATOR_PATTERN})?\s*"
    rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_PATTERN})",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"[。!！?？\n]+|\.(?=\s|$)")
_BEHAVIOR_WORDS = ("通信中断", "失联", "故障", "中断", "自动返航", "返航", "恢复", "after", "when")
_MISSION_WORDS = ("设计", "研制", "开发", "系统", "无人机", "侦察", "任务", "mission", "system")

_OPERATOR_ALIASES = {
    "不超过": "<=",
    "不得大于": "<=",
    "不高于": "<=",
    "不大于": "<=",
    "小于等于": "<=",
    "≤": "<=",
    "<=": "<=",
    "至少": ">=",
    "不少于": ">=",
    "不低于": ">=",
    "大于等于": ">=",
    "以上": ">=",
    "≥": ">=",
    ">=": ">=",
    "等于": "==",
    "==": "==",
    "<": "<",
    ">": ">",
}
_UNIT_ALIASES = {"秒": "s", "米": "m", "千克": "kg", "pa": "Pa"}


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
    requirements: tuple[StructuredRequirement, ...]
    attributes: tuple[RequirementAttribute, ...]
    constraints: tuple[RequirementConstraint, ...]

    @property
    def metrics(self) -> tuple[NormalizedMetric, ...]:
        return tuple(metric for clause in self.clauses for metric in clause.normalized_metrics)


def _regions(value: str | Sequence[DocumentRegion]) -> tuple[DocumentRegion, ...]:
    if isinstance(value, str):
        return (
            DocumentRegion(
                id="region-1",
                artifact_id="",
                page=1,
                kind="paragraph",
                locator="paragraph-1",
                text=value,
            ),
        )
    result: list[DocumentRegion] = []
    for index, raw in enumerate(value, start=1):
        if isinstance(raw, DocumentRegion):
            result.append(raw)
            continue
        if isinstance(raw, dict):
            result.append(
                DocumentRegion(
                    id=str(raw.get("id") or f"region-{index}"),
                    artifact_id=str(raw.get("artifact_id", "")),
                    page=raw.get("page"),
                    kind=str(raw.get("kind", "paragraph")),
                    locator=str(raw.get("locator", f"paragraph-{index}")),
                    text=str(raw.get("text", "")),
                    bbox=tuple(raw.get("bbox", ())),
                    confidence=float(raw.get("confidence", 1.0)),
                )
            )
            continue
        raise TypeError("requirement input must contain DocumentRegion values")
    return tuple(result)


def _clean_name(value: str) -> str:
    return value.strip(" \t:：-—，,；;")


def _metrics(text: str) -> tuple[NormalizedMetric, ...]:
    result: list[NormalizedMetric] = []
    for match in _METRIC_PATTERN.finditer(text):
        name = _clean_name(match.group("name"))
        # A conjunction can be captured as part of a metric name when the
        # source omitted punctuation.  It is not part of the engineering term.
        name = re.sub(r"^(?:且|并且|以及|and)\s*", "", name, flags=re.IGNORECASE)
        if not name:
            continue
        operator = _OPERATOR_ALIASES.get(match.group("operator") or "", "==")
        unit = _UNIT_ALIASES.get(match.group("unit"), match.group("unit"))
        result.append(
            NormalizedMetric(
                name=name,
                value=float(match.group("value")),
                unit=unit,
                operator=operator,
                source_text=match.group(0).strip(),
            )
        )
    return tuple(result)


def _kind(text: str, metrics: tuple[NormalizedMetric, ...]) -> str:
    lowered = text.casefold()
    if any(word.casefold() in lowered for word in _BEHAVIOR_WORDS):
        return "behavior"
    if metrics:
        return "metric"
    if any(word.casefold() in lowered for word in _MISSION_WORDS):
        return "mission"
    return "context"


def _parts(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _SENTENCE_BOUNDARY_PATTERN.split(text) if part.strip())


def _clause_id(source_region_id: str, local_ordinal: int, clause: str, metrics: tuple[NormalizedMetric, ...]) -> str:
    normalized = " ".join(clause.split())
    return f"clause-{canonical_hash((source_region_id, local_ordinal, normalized, metrics))[:12]}"


class RequirementClauseSplitter:
    """Split text or document regions into stable, reviewable clauses."""

    def split(self, value: str | Sequence[DocumentRegion]) -> tuple[RequirementClause, ...]:
        clauses: list[RequirementClause] = []
        ordinal = 0
        for region in _regions(value):
            local_ordinal = 0
            for text in _parts(region.text):
                local_ordinal += 1
                ordinal += 1
                metrics = _metrics(text)
                clauses.append(
                    RequirementClause(
                        id=_clause_id(region.id, local_ordinal, text, metrics),
                        source_region_id=region.id,
                        ordinal=ordinal,
                        text=text,
                        kind=_kind(text, metrics),
                        normalized_metrics=metrics,
                    )
                )
        return tuple(clauses)

    def analyze(self, value: str | Sequence[DocumentRegion]) -> ClauseAnalysis:
        clauses = self.split(value)
        requirements: list[StructuredRequirement] = []
        attributes: list[RequirementAttribute] = []
        constraints: list[RequirementConstraint] = []
        for clause in clauses:
            region = DocumentRegion(
                id=clause.source_region_id,
                artifact_id="",
                page=1,
                kind="paragraph",
                locator=clause.id,
                text=clause.text,
            )
            extracted = extract_requirement_candidates({"document_regions": (region,)})
            if not extracted:
                continue
            requirement = extracted[0]
            requirements.append(requirement)
            for metric in clause.normalized_metrics:
                minimum = str(metric.value) if metric.operator in {">=", ">"} else ""
                maximum = str(metric.value) if metric.operator in {"<=", "<"} else ""
                value_text = str(metric.value) if metric.operator == "==" else ""
                attributes.append(
                    RequirementAttribute.from_fields(
                        requirement_id=requirement.id,
                        name=metric.name,
                        value=value_text,
                        unit=metric.unit,
                        minimum=minimum,
                        maximum=maximum,
                        source_region_ids=(clause.source_region_id,),
                    )
                )
                constraints.append(
                    RequirementConstraint.from_fields(
                        requirement_ids=(requirement.id,),
                        constraint_type="behavior" if clause.kind == "behavior" else "performance",
                        expression=f"{metric.name} {metric.operator} {metric.value} {metric.unit}",
                        explicitness="explicit",
                        source_region_ids=(clause.source_region_id,),
                    )
                )
        return ClauseAnalysis(tuple(clauses), tuple(requirements), tuple(attributes), tuple(constraints))


__all__ = [
    "ClauseAnalysis",
    "NormalizedMetric",
    "RequirementClause",
    "RequirementClauseSplitter",
]
