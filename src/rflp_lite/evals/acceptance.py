"""Offline acceptance checks for the typed Harness model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    status: str
    coverage: Mapping[str, object]
    diagnostics: tuple[str, ...] = ()
    traceability: tuple[Mapping[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "coverage": dict(self.coverage),
            "diagnostics": list(self.diagnostics),
            "traceability": [dict(item) for item in self.traceability],
        }


def run_acceptance(graph: ModelGraph, fixture: Mapping[str, object]) -> AcceptanceReport:
    active = tuple(entity for entity in graph.entities if entity.meta.status is not EntityStatus.DEPRECATED)
    names = {entity.meta.name for entity in active}
    expected_system = str(fixture.get("system", "")).strip()
    system_ok = not expected_system or any(
        entity.kind is EntityKind.SYSTEM and entity.meta.name == expected_system for entity in active
    )
    stakeholders = {str(value) for value in fixture.get("stakeholders", ())}
    lifecycle = {str(value) for value in fixture.get("lifecycle_stages", ())}
    scenarios = {str(value) for value in fixture.get("scenarios", ())}
    requirements = fixture.get("requirements", ())
    present_by_kind = {
        kind.value: sum(entity.kind is kind for entity in active)
        for kind in EntityKind
    }
    checks = {
        "system": system_ok,
        "stakeholders": not stakeholders or stakeholders <= names,
        "lifecycle_stages": not lifecycle or lifecycle <= names,
        "scenarios": not scenarios or scenarios <= names,
        "requirements": not requirements or present_by_kind[EntityKind.REQUIREMENT.value] >= len(requirements),
    }
    diagnostics = tuple(f"acceptance_missing:{key}" for key, passed in checks.items() if not passed)
    traceability = tuple(
        {
            "requirement_id": str(item.get("id", "")),
            "matched": any(
                entity.kind is EntityKind.REQUIREMENT
                and (str(item.get("statement", "")) in entity.meta.name or entity.meta.name in str(item.get("statement", "")))
                for entity in active
            ),
        }
        for item in requirements
        if isinstance(item, Mapping)
    )
    return AcceptanceReport("passed" if not diagnostics else "failed", checks, diagnostics, traceability)
