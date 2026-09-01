"""Versioned historical requirement and combat-scenario records."""

from __future__ import annotations

from dataclasses import dataclass


def _texts(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split("|") if item.strip())
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


@dataclass(frozen=True, slots=True)
class RequirementHistoryRecord:
    id: str
    dataset_id: str
    dataset_version: str
    statement: str
    subject: str = ""
    predicate: str = ""
    attributes: tuple[tuple[str, str], ...] = ()
    constraints: tuple[str, ...] = ()
    trace_links: tuple[tuple[str, str, str], ...] = ()
    applicability: tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: dict[str, object], *, dataset_id: str, dataset_version: str) -> "RequirementHistoryRecord":
        record_id = str(row.get("id", "")).strip()
        statement = str(row.get("statement", row.get("text", ""))).strip()
        if not record_id or not statement:
            raise ValueError("history record requires id and statement")
        attrs = row.get("attributes", ())
        pairs: list[tuple[str, str]] = []
        if isinstance(attrs, dict):
            pairs = [(str(key), str(value)) for key, value in attrs.items()]
        elif isinstance(attrs, (list, tuple)):
            pairs = [(str(item[0]), str(item[1])) for item in attrs if isinstance(item, (list, tuple)) and len(item) >= 2]
        return cls(record_id, str(dataset_id), str(dataset_version), statement, str(row.get("subject", "")), str(row.get("predicate", "")), tuple(pairs), _texts(row.get("constraints")), (), _texts(row.get("applicability")))


@dataclass(frozen=True, slots=True)
class CombatScenarioRecord:
    id: str
    dataset_id: str
    dataset_version: str
    title: str
    mission: str = ""
    actors: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    alternate_steps: tuple[str, ...] = ()
    failure_steps: tuple[str, ...] = ()
    recovery_steps: tuple[str, ...] = ()
    applicability: tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: dict[str, object], *, dataset_id: str, dataset_version: str) -> "CombatScenarioRecord":
        record_id = str(row.get("id", "")).strip()
        title = str(row.get("title", row.get("name", ""))).strip()
        if not record_id or not title:
            raise ValueError("scenario record requires id and title")
        return cls(record_id, str(dataset_id), str(dataset_version), title, str(row.get("mission", "")), _texts(row.get("actors")), _texts(row.get("preconditions")), _texts(row.get("steps")), _texts(row.get("alternate_steps")), _texts(row.get("failure_steps")), _texts(row.get("recovery_steps")), _texts(row.get("applicability")))


@dataclass(frozen=True, slots=True)
class RequirementMatch:
    record_id: str
    dataset_id: str
    dataset_version: str
    score: float
    matched_terms: tuple[str, ...] = ()
    matched_numeric_features: tuple[tuple[float, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioMatch:
    record_id: str
    dataset_id: str
    dataset_version: str
    score: float
    matched_terms: tuple[str, ...] = ()
    covered_requirement_ids: tuple[str, ...] = ()


__all__ = ["RequirementHistoryRecord", "CombatScenarioRecord", "RequirementMatch", "ScenarioMatch"]
