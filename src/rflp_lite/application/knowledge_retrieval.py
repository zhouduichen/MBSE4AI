"""Deterministic, explainable retrieval over versioned knowledge records."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from rflp_lite.domain.knowledge import CombatScenarioRecord, RequirementHistoryRecord, RequirementMatch, ScenarioMatch

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}")
_NUMBER_UNIT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>km/h|m/s|mm|m|kg|N|Pa|%|°)?", re.IGNORECASE)


def normalized_features(text: str) -> tuple[frozenset[str], tuple[tuple[float, str], ...]]:
    terms = frozenset(match.group(0).casefold() for match in _TOKEN.finditer(str(text)))
    numbers = tuple((float(match.group("value")), (match.group("unit") or "").casefold()) for match in _NUMBER_UNIT.finditer(str(text)))
    return terms, numbers


def _record_text(record: RequirementHistoryRecord) -> str:
    attrs = " ".join(f"{key} {value}" for key, value in record.attributes)
    return " ".join((record.statement, record.subject, record.predicate, attrs, *record.constraints, *record.applicability))


def _score(query_terms, query_numbers, record_terms, record_numbers) -> tuple[float, tuple[str, ...], tuple[tuple[float, str], ...]]:
    matched_terms = tuple(sorted(query_terms & record_terms))
    matched_numbers = tuple(item for item in query_numbers if item in record_numbers)
    term_score = len(matched_terms) / max(len(query_terms), 1)
    numeric_score = len(matched_numbers) / max(len(query_numbers), 1)
    return round(0.75 * term_score + 0.25 * numeric_score, 8), matched_terms, matched_numbers


def retrieve_requirements(query: Mapping[str, object], records: Iterable[RequirementHistoryRecord], limit: int = 5) -> tuple[RequirementMatch, ...]:
    text = " ".join(str(query.get(key, "")) for key in ("statement", "subject", "predicate"))
    attrs = query.get("attributes", ())
    if isinstance(attrs, (list, tuple)):
        text += " " + " ".join(" ".join(str(part) for part in item) if isinstance(item, (list, tuple)) else str(item) for item in attrs)
    query_terms, query_numbers = normalized_features(text)
    matches = []
    for record in records:
        terms, numbers = normalized_features(_record_text(record))
        score, matched_terms, matched_numbers = _score(query_terms, query_numbers, terms, numbers)
        matches.append(RequirementMatch(record.id, record.dataset_id, record.dataset_version, score, matched_terms, matched_numbers))
    return tuple(sorted(matches, key=lambda item: (-item.score, item.record_id))[: max(0, int(limit))])


def retrieve_scenarios(requirements: Iterable[Mapping[str, object]], records: Iterable[CombatScenarioRecord], limit: int = 5) -> tuple[ScenarioMatch, ...]:
    reqs = tuple(requirements)
    query_text = " ".join(str(item.get("statement", item.get("object", ""))) for item in reqs)
    query_terms, _ = normalized_features(query_text)
    req_ids = tuple(str(item.get("id", "")) for item in reqs if str(item.get("id", "")))
    results = []
    for record in records:
        text = " ".join((record.title, record.mission, *record.actors, *record.preconditions, *record.steps, *record.alternate_steps, *record.failure_steps, *record.recovery_steps, *record.applicability))
        terms, _ = normalized_features(text)
        matched = tuple(sorted(query_terms & terms))
        score = round(len(matched) / max(len(query_terms), 1), 8)
        results.append(ScenarioMatch(record.id, record.dataset_id, record.dataset_version, score, matched, req_ids if matched else ()))
    return tuple(sorted(results, key=lambda item: (-item.score, item.record_id))[: max(0, int(limit))])


class RequirementRetriever:
    def retrieve(self, query, records, limit=5):
        return retrieve_requirements(query, records, limit)


class ScenarioRetriever:
    def retrieve(self, requirements, records, limit=5):
        return retrieve_scenarios(requirements, records, limit)


__all__ = ["normalized_features", "retrieve_requirements", "retrieve_scenarios", "RequirementRetriever", "ScenarioRetriever"]
