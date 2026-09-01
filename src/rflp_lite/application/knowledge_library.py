"""Mapping and validation for versioned knowledge dataset records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from rflp_lite.domain.knowledge import CombatScenarioRecord, RequirementHistoryRecord


def import_requirement_history(rows: Iterable[Mapping[str, object]], dataset_id: str, dataset_version: str = "") -> tuple[RequirementHistoryRecord, ...]:
    return tuple(RequirementHistoryRecord.from_row(dict(row), dataset_id=dataset_id, dataset_version=dataset_version) for row in rows)


def import_combat_scenarios(rows: Iterable[Mapping[str, object]], dataset_id: str, dataset_version: str = "") -> tuple[CombatScenarioRecord, ...]:
    return tuple(CombatScenarioRecord.from_row(dict(row), dataset_id=dataset_id, dataset_version=dataset_version) for row in rows)


__all__ = ["import_requirement_history", "import_combat_scenarios"]
