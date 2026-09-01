"""Read-only ports for versioned engineering knowledge datasets."""

from __future__ import annotations

from typing import Protocol

from rflp_lite.domain.knowledge import CombatScenarioRecord, RequirementHistoryRecord


class RequirementHistoryRepositoryPort(Protocol):
    def dataset_id(self) -> str: ...
    def dataset_version(self) -> str: ...
    def records(self) -> tuple[RequirementHistoryRecord, ...]: ...


class CombatScenarioRepositoryPort(Protocol):
    def dataset_id(self) -> str: ...
    def dataset_version(self) -> str: ...
    def records(self) -> tuple[CombatScenarioRecord, ...]: ...


__all__ = ["RequirementHistoryRepositoryPort", "CombatScenarioRepositoryPort"]
