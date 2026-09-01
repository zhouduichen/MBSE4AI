"""Validated, cross-run-stable customer acceptance gold contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping

from rflp_lite.domain.errors import ContractViolation


def normalize_acceptance_text(value: object) -> str:
    """Normalize whitespace and terminal punctuation for deterministic matching."""

    text = "" if value is None else str(value)
    return "".join(text.split()).rstrip("。.!！?？;；")


def _required_text(value: object, field: str) -> str:
    text = normalize_acceptance_text(value)
    if not text:
        raise ContractViolation(f"gold {field} is required")
    return text


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractViolation(f"gold {field} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class GoldRequirement:
    key: str
    statement: str
    accepted_statements: tuple[str, ...]
    source_anchor: str
    details: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class GoldContract:
    version: int
    corpus_mode: str
    details_mode: str
    requirements: tuple[GoldRequirement, ...]
    thresholds: dict[str, float]
    mbse_expectations: dict[str, object]


@dataclass(frozen=True, slots=True)
class RequirementMatchReport:
    matched: tuple[str, ...]
    unmatched_actual: tuple[str, ...]
    unmatched_expected: tuple[str, ...]
    pair_diagnostics: tuple[dict[str, object], ...]
    provenance_complete: int


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ContractViolation(f"gold {field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"gold {field} must be numeric") from exc
    if not math.isfinite(number):
        raise ContractViolation(f"gold {field} must be finite")
    return number


def validate_gold_payload(payload: object) -> GoldContract:
    """Validate and freeze a complete v3 gold payload."""

    root = _mapping(payload, "payload")
    if root.get("version") != 3:
        raise ContractViolation("gold contract version 3 is required")
    if root.get("corpus_mode") != "complete":
        raise ContractViolation("gold corpus_mode must be complete")
    if root.get("details_mode") != "complete":
        raise ContractViolation("gold details_mode must be complete")

    raw_requirements = root.get("requirements")
    if not isinstance(raw_requirements, (list, tuple)) or not raw_requirements:
        raise ContractViolation("gold requirements must be a non-empty array")
    requirements: list[GoldRequirement] = []
    keys: set[str] = set()
    anchors: set[str] = set()
    statements: set[str] = set()
    for index, raw in enumerate(raw_requirements):
        item = _mapping(raw, f"requirements[{index}]")
        key = _required_text(item.get("key"), f"requirements[{index}].key")
        statement = _required_text(item.get("statement"), f"requirements[{index}].statement")
        anchor = _required_text(item.get("source_anchor"), f"requirements[{index}].source_anchor")
        if key in keys:
            raise ContractViolation(f"duplicate gold requirement key: {key}")
        if anchor in anchors:
            raise ContractViolation(f"duplicate gold source anchor: {anchor}")
        if statement in statements:
            raise ContractViolation(f"duplicate gold statement: {statement}")
        keys.add(key)
        anchors.add(anchor)
        statements.add(statement)
        raw_accepted = item.get("accepted_statements", ())
        if not isinstance(raw_accepted, (list, tuple)):
            raise ContractViolation(f"gold requirements[{index}].accepted_statements must be an array")
        accepted: list[str] = []
        for candidate in raw_accepted:
            text = _required_text(candidate, f"requirements[{index}].accepted_statements")
            if text not in accepted and text != statement:
                accepted.append(text)
        raw_details = item.get("details", ())
        if not isinstance(raw_details, (list, tuple)):
            raise ContractViolation(f"gold requirements[{index}].details must be an array")
        details: list[dict[str, object]] = []
        for detail_index, detail in enumerate(raw_details):
            detail_map = _mapping(detail, f"requirements[{index}].details[{detail_index}]")
            details.append(dict(detail_map))
        requirements.append(
            GoldRequirement(key, statement, tuple(accepted), anchor, tuple(details))
        )

    raw_thresholds = root.get("thresholds", {})
    thresholds: dict[str, float] = {}
    if raw_thresholds is not None:
        for name, value in _mapping(raw_thresholds, "thresholds").items():
            thresholds[str(name)] = _finite_number(value, f"thresholds.{name}")
    raw_mbse = root.get("mbse_expectations", {})
    mbse = dict(_mapping(raw_mbse, "mbse_expectations")) if raw_mbse is not None else {}
    return GoldContract(
        version=3,
        corpus_mode="complete",
        details_mode="complete",
        requirements=tuple(requirements),
        thresholds=thresholds,
        mbse_expectations=mbse,
    )


def load_gold_contract(path) -> GoldContract:
    """Read and validate a JSON gold contract from ``path``."""

    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"unable to read gold contract: {exc}") from exc
    return validate_gold_payload(payload)


def _actual_value(item: object, name: str, default: object = "") -> object:
    return item.get(name, default) if isinstance(item, Mapping) else default


def _actual_id(item: object, index: int) -> str:
    value = _actual_value(item, "id") or _actual_value(item, "source_region_id") or _actual_value(item, "source_span_id")
    return str(value or f"actual-{index + 1}")


def _source_text(item: object, source_text_by_region: Mapping[str, object]) -> str:
    direct = _actual_value(item, "source_text")
    if direct:
        return str(direct)
    for field in ("source_region_id", "source_span_id"):
        source_id = str(_actual_value(item, field, "") or "")
        if source_id and source_id in source_text_by_region:
            return str(source_text_by_region[source_id])
    return ""


def _statement_candidates(requirement: GoldRequirement) -> tuple[str, ...]:
    return (requirement.statement, *requirement.accepted_statements)


def _statement_similarity(actual: str, expected: str) -> float:
    left = normalize_acceptance_text(actual)
    right = normalize_acceptance_text(expected)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    shorter, longer = sorted((left, right), key=len)
    if shorter not in longer or len(shorter) / len(longer) < 0.8:
        return 0.0
    return len(shorter) / len(longer)


def match_requirement_items(
    actual,
    expected,
    source_text_by_region: Mapping[str, object] | None = None,
) -> RequirementMatchReport:
    """Pair actual requirements to v3 gold records by source anchor and text."""

    actual_items = tuple(actual)
    expected_items = tuple(
        item if isinstance(item, GoldRequirement) else GoldRequirement(
            key=_required_text(_actual_value(item, "key"), "requirement.key"),
            statement=_required_text(_actual_value(item, "statement"), "requirement.statement"),
            accepted_statements=tuple(
                normalize_acceptance_text(value)
                for value in (_actual_value(item, "accepted_statements", ()) or ())
            ),
            source_anchor=_required_text(_actual_value(item, "source_anchor"), "requirement.source_anchor"),
            details=tuple(dict(value) for value in (_actual_value(item, "details", ()) or ()) if isinstance(value, Mapping)),
        )
        for item in expected
    )
    source_map = source_text_by_region or {}
    possible: list[tuple[float, str, str, int, GoldRequirement]] = []
    provenance_ok: set[int] = set()
    diagnostics: list[dict[str, object]] = []
    for index, item in enumerate(actual_items):
        actual_id = _actual_id(item, index)
        source_text = normalize_acceptance_text(_source_text(item, source_map))
        statement = normalize_acceptance_text(_actual_value(item, "statement", _actual_value(item, "object", "")))
        anchor_matches = [
            requirement
            for requirement in expected_items
            if normalize_acceptance_text(requirement.source_anchor) in source_text
        ]
        if anchor_matches and source_text and _actual_value(item, "source_region_id", _actual_value(item, "source_span_id", "")):
            provenance_ok.add(index)
        for requirement in anchor_matches:
            scores = [_statement_similarity(statement, candidate) for candidate in _statement_candidates(requirement)]
            score = max(scores, default=0.0)
            if score:
                possible.append((score, requirement.key, actual_id, index, requirement))
        diagnostics.append({
            "actual_id": actual_id,
            "source_text_found": bool(source_text),
            "anchor_candidates": tuple(item.key for item in anchor_matches),
        })

    used_actual: set[int] = set()
    used_expected: set[str] = set()
    matched: list[str] = []
    for score, key, actual_id, index, _requirement in sorted(possible, key=lambda item: (-item[0], item[1], item[2])):
        if index in used_actual or key in used_expected:
            continue
        used_actual.add(index)
        used_expected.add(key)
        matched.append(key)
        diagnostics[index]["matched_key"] = key
        diagnostics[index]["similarity"] = round(score, 4)
    actual_ids = {_actual_id(item, index) for index, item in enumerate(actual_items)}
    return RequirementMatchReport(
        matched=tuple(sorted(matched)),
        unmatched_actual=tuple(sorted(actual_ids - {diagnostics[index]["actual_id"] for index in used_actual})),
        unmatched_expected=tuple(sorted(requirement.key for requirement in expected_items if requirement.key not in used_expected)),
        pair_diagnostics=tuple(diagnostics),
        provenance_complete=round(len(provenance_ok) * 100 / len(actual_items)) if actual_items else 0,
    )


__all__ = [
    "GoldContract",
    "GoldRequirement",
    "RequirementMatchReport",
    "load_gold_contract",
    "match_requirement_items",
    "normalize_acceptance_text",
    "validate_gold_payload",
]
