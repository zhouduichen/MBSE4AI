"""Requirement quality, provenance, derivation, and assumption checks."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .common import by_id, by_kind, finding, payload, ratio, text_of


_VAGUE = re.compile(r"很安全|比较可靠|良好性能|方便使用|good performance|very safe|reliable")
_CONJUNCTION = re.compile(r"并且|以及|同时|\band\b|\bor\b")
_HARD_ASSUMPTION = re.compile(r"必须.*(激光雷达|雷达|64线|lidar|specific vendor)|\b64[- ]line\b", re.I)


def _requirement_statement(entity: Mapping[str, object]) -> str:
    value = payload(entity).get("statement") or entity.get("name", "")
    return text_of(value).strip()


def _has_source(entity: Mapping[str, object], graph: Mapping[str, object]) -> bool:
    source_ids = entity.get("source_ids", ())
    if isinstance(source_ids, list | tuple) and any(str(item).strip() for item in source_ids):
        return True
    entity_id = str(entity.get("id", ""))
    return any(
        str(item.get("source_id", "")) == entity_id or str(item.get("target_id", "")) == entity_id
        for item in graph.get("relations", ()) if isinstance(item, Mapping)
    )


def _derived_requirement_review(
    graph: Mapping[str, object],
) -> tuple[int, float, list[str], list[str]]:
    """Measure whether technical requirements are real derived model elements.

    A technical requirement is useful only when it preserves both sides of
    the derivation: a typed parent requirement and the physical candidate
    whose implementation or constraint it describes.  The payload fields are
    useful for the UI, but the graph relations remain authoritative for
    precision.  A feasibility placeholder may have no numeric constraint yet;
    its typed physical scope must still be explicit.
    """

    index = by_id(graph)
    technical = [
        item for item in by_kind(graph, "requirement")
        if str(payload(item).get("level", "")).strip().casefold() == "technical"
    ]
    edge_set = {
        (
            str(item.get("source_id", "")),
            str(item.get("predicate", "")),
            str(item.get("target_id", "")),
        )
        for item in graph.get("relations", ())
        if isinstance(item, Mapping)
    }
    valid: list[str] = []
    invalid: list[str] = []
    for entity in technical:
        entity_id = str(entity.get("id", ""))
        entity_payload = payload(entity)
        parent_ids = {
            str(item)
            for item in entity_payload.get("source_requirement_ids", ())
            if str(item) in index
            and str(item) != entity_id
            and str(index[str(item)].get("kind", "")) == "requirement"
        }
        physical_ids = {
            str(item)
            for item in entity_payload.get("source_physical_ids", ())
            if str(item) in index
            and str(index[str(item)].get("kind", "")) == "physical_block"
        }
        has_parent_edges = any(
            (entity_id, "derivedFrom", parent_id) in edge_set
            for parent_id in parent_ids
        )
        has_physical_edges = any(
            (entity_id, "satisfiedBy", physical_id) in edge_set
            for physical_id in physical_ids
        )
        if parent_ids and physical_ids and has_parent_edges and has_physical_edges:
            valid.append(entity_id)
        else:
            invalid.append(entity_id)
    total = len(technical)
    precision = len(valid) / total if total else 1.0
    return total, round(precision, 6), valid, invalid


def validate_requirements(graph: Mapping[str, object], expectations: Mapping[str, object] | None = None) -> dict[str, object]:
    requirements = by_kind(graph, "requirement")
    clear: list[str] = []
    atomic: list[str] = []
    verifiable: list[str] = []
    sourced: list[str] = []
    unsupported: list[str] = []
    duplicate_keys: dict[str, list[str]] = {}
    for entity in requirements:
        entity_id = str(entity.get("id", ""))
        statement = _requirement_statement(entity)
        lower = statement.casefold()
        if statement and not _VAGUE.search(statement) and statement not in {"待确认", "to be confirmed"}:
            clear.append(entity_id)
        if len(_CONJUNCTION.findall(lower)) <= 1 and not re.search(r"或", statement):
            atomic.append(entity_id)
        req_payload = payload(entity)
        method = text_of(req_payload.get("verification_method", "")).strip()
        has_metric = isinstance(req_payload.get("metric"), Mapping) or bool(re.search(r"\d+\s*(ms|秒|分钟|小时|h|kg|w|wh|%)", statement, re.I))
        if method and (has_metric or method.casefold() not in {"review", "待确认"}):
            verifiable.append(entity_id)
        if _has_source(entity, graph):
            sourced.append(entity_id)
        if _HARD_ASSUMPTION.search(statement) and not (_has_source(entity, graph) or req_payload.get("rationale")):
            unsupported.append(entity_id)
        key = re.sub(r"\W+", "", statement.casefold())
        if key:
            duplicate_keys.setdefault(key, []).append(entity_id)
    duplicate_ids = [item for values in duplicate_keys.values() if len(values) > 1 for item in values]
    derived_count, derived_precision, derived_valid_ids, derived_invalid_ids = _derived_requirement_review(graph)
    total = len(requirements)
    validity = ratio(len(set(clear) & set(sourced)), total)
    atomicity = ratio(len(atomic), total)
    verifiability = ratio(len(verifiable), total)
    unsupported_rate = ratio(len(unsupported), total) if total else 0.0
    return {
        "requirement_count": total,
        "requirement_validity": validity,
        "requirement_atomicity": atomicity,
        "requirement_verifiability": verifiability,
        "unsupported_hard_assumption_rate": unsupported_rate,
        "clear_ids": clear,
        "atomic_ids": atomic,
        "verifiable_ids": verifiable,
        "sourced_ids": sourced,
        "unsupported_ids": unsupported,
        "duplicate_ids": duplicate_ids,
        "derived_requirement_count": derived_count,
        "derived_requirement_precision": derived_precision,
        "derived_requirement_valid_ids": derived_valid_ids,
        "derived_requirement_invalid_ids": derived_invalid_ids,
        "findings": [
            finding("T4", str(graph.get("project_id", "")), "PASS" if validity >= 0.90 and atomicity >= 0.85 and verifiability >= 0.90 else "FAIL", severity="P1", category="requirement_quality", expected={"validity": ">= 90%", "atomicity": ">= 85%", "verifiability": ">= 90%"}, actual={"validity": validity, "atomicity": atomicity, "verifiability": verifiability}, root_cause="requirement fields are vague, compound, unverifiable, or unproven" if validity < 0.90 or atomicity < 0.85 or verifiability < 0.90 else "", recommended_fix="Normalize atomic shall-statements with source and verification criteria."),
            finding("T19", str(graph.get("project_id", "")), "PASS" if unsupported_rate <= 0.05 else "FAIL", severity="P1", category="unsupported_assumption", expected="unsupported hard assumption rate <= 5%", actual=unsupported_rate, related_elements=unsupported, root_cause="hard requirements lack source or engineering rationale" if unsupported else "", recommended_fix="Attach stakeholder/scenario/evidence provenance or mark the item as an explicit assumption."),
            finding("T8", str(graph.get("project_id", "")), "PASS" if derived_precision >= 0.80 else "FAIL", severity="P1", category="derived_requirement_precision", expected=">= 80% technical requirements preserve typed parent and physical derivation", actual={"precision": derived_precision, "count": derived_count, "valid_ids": derived_valid_ids, "invalid_ids": derived_invalid_ids}, related_elements=derived_invalid_ids, root_cause="technical requirements are not connected to a source requirement and physical candidate" if derived_invalid_ids else "", recommended_fix="Persist source_requirement_ids/source_physical_ids and derivedFrom/satisfiedBy edges for each technical requirement."),
        ],
    }
