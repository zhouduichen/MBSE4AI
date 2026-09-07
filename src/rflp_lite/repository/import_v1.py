"""One-time importer from the legacy JSON aggregate to Repository v2."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.domain.entities import EntityKind, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.repository.sqlite import SQLiteModelRepository


_KIND_MAP = {
    "system": EntityKind.SYSTEM,
    "stakeholders": EntityKind.STAKEHOLDER,
    "requirements": EntityKind.REQUIREMENT,
    "functions": EntityKind.FUNCTION,
    "logical_components": EntityKind.LOGICAL_COMPONENT,
    "physical_components": EntityKind.PHYSICAL_BLOCK,
    "interfaces": EntityKind.INTERFACE,
}


def import_legacy_state(
    repository: SQLiteModelRepository,
    project_id: str,
    state: Mapping[str, object],
) -> tuple[str, ...]:
    """Import only representable entities and relations, returning diagnostics."""

    repository.ensure_project(project_id, str(state.get("name", project_id)))
    operations: list[AddEntity | Relate] = []
    diagnostics: list[str] = []
    for section, kind in _KIND_MAP.items():
        values = state.get(section, [])
        if isinstance(values, Mapping):
            values = [values]
        if not isinstance(values, (list, tuple)):
            continue
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            name = str(raw.get("name", raw.get("id", ""))).strip()
            if not name:
                diagnostics.append(f"dropped {section} item without name")
                continue
            entity_id = str(raw.get("id", "")).strip()
            entity = make_entity(kind, name, dict(raw), producer=Producer.IMPORT)
            if entity_id:
                from dataclasses import replace
                entity = replace(entity, meta=replace(entity.meta, id=entity_id))
            operations.append(AddEntity(entity))
    current = repository.load_graph(project_id)
    patch = Patch.create(project_id, "migration.v1", tuple(operations), "one-time v1 import", current.revision)
    if operations:
        repository.append_patch(project_id, patch, current.revision)
    diagnostics.append("legacy fields not representable in v2 were not imported")
    return tuple(diagnostics)
