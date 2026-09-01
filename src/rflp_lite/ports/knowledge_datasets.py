"""Read-only ports for versioned engineering knowledge datasets."""

from __future__ import annotations

from typing import Protocol
from collections.abc import Iterable, Mapping

from rflp_lite.domain.knowledge import CombatScenarioRecord, RequirementHistoryRecord


class RequirementHistoryRepositoryPort(Protocol):
    def dataset_id(self) -> str: ...
    def dataset_version(self) -> str: ...
    def records(self) -> tuple[RequirementHistoryRecord, ...]: ...


class CombatScenarioRepositoryPort(Protocol):
    def dataset_id(self) -> str: ...
    def dataset_version(self) -> str: ...
    def records(self) -> tuple[CombatScenarioRecord, ...]: ...


class RequirementRetrieverPort(Protocol):
    def retrieve(self, query: Mapping[str, object], records: Iterable[RequirementHistoryRecord], limit: int = 5): ...


class ScenarioRetrieverPort(Protocol):
    def retrieve(self, requirements: Iterable[Mapping[str, object]], records: Iterable[CombatScenarioRecord], limit: int = 5): ...


__all__ = ["RequirementHistoryRepositoryPort", "CombatScenarioRepositoryPort", "RequirementRetrieverPort", "ScenarioRetrieverPort"]
