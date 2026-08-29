"""Transactional commands for human deletion previews and restoration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rflp_lite.application.entity_deletion import (
    delete_entity,
    preview_entity_deletion,
    restore_entity,
)
from rflp_lite.application.workbench import MutationKind, MutationResult, WorkbenchCommitCoordinator
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class PreviewEntityDeletionCommand:
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class DeleteEntityCommand:
    entity_type: str
    entity_id: str
    plan_hash: str
    expected_revision: int | None = None


@dataclass(frozen=True, slots=True)
class RestoreEntityCommand:
    entity_type: str
    entity_id: str
    expected_revision: int | None = None


class PreviewEntityDeletionUseCase:
    def __init__(self, repository: Any):
        self.repository = repository

    def execute(self, command: PreviewEntityDeletionCommand) -> dict[str, object]:
        state = self.repository.load_workbench()
        if not isinstance(state, dict):
            raise ContractViolation("requirements workbench is empty")
        return preview_entity_deletion(state, command.entity_type, command.entity_id)


class DeleteEntityUseCase:
    def __init__(self, repository: Any):
        self.repository = repository

    def execute(self, command: DeleteEntityCommand) -> dict[str, object]:
        coordinator = WorkbenchCommitCoordinator(self.repository, "")
        snapshot = coordinator.snapshot()
        if snapshot is None:
            raise ContractViolation("requirements workbench is empty")
        expected_revision = (
            snapshot.revision
            if command.expected_revision is None
            else command.expected_revision
        )
        affected: dict[str, object] = {}

        def mutation(state: dict[str, object]) -> MutationResult:
            nonlocal affected
            preview = preview_entity_deletion(state, command.entity_type, command.entity_id)
            affected = dict(preview["affected"])
            updated = delete_entity(
                state, command.entity_type, command.entity_id, command.plan_hash
            )
            return MutationResult(
                state=updated,
                changed_ids=(command.entity_id,),
                invalidated_sections=("rflp", "mbse", "baseline", "project"),
                mutation_kind=MutationKind.HUMAN_CONTENT,
            )

        event = {
            "requirement": "requirements.deleted",
            "scenario": "scenario.deleted",
            "stakeholder": "stakeholder.deleted",
        }.get(command.entity_type, "entity.deleted")
        return coordinator.commit(
            mutation,
            expected_revision=expected_revision,
            expected_content_revision=snapshot.content_revision,
            event=event,
            audit_payload={
                "entity_type": command.entity_type,
                "entity_id": command.entity_id,
                "plan_hash": command.plan_hash,
                "affected": affected,
            },
            deleted_requirement_ids=(command.entity_id,)
            if command.entity_type == "requirement"
            else (),
        ).state


class RestoreEntityUseCase:
    def __init__(self, repository: Any):
        self.repository = repository

    def execute(self, command: RestoreEntityCommand) -> dict[str, object]:
        coordinator = WorkbenchCommitCoordinator(self.repository, "")
        snapshot = coordinator.snapshot()
        if snapshot is None:
            raise ContractViolation("requirements workbench is empty")
        expected_revision = (
            snapshot.revision
            if command.expected_revision is None
            else command.expected_revision
        )

        def mutation(state: dict[str, object]) -> MutationResult:
            active_group = {
                "stakeholder": "stakeholders",
                "requirement": "claims",
                "scenario": "scenarios",
            }.get(command.entity_type, "")
            active = any(
                str(item.get("id", "")) == command.entity_id
                for item in state.get(active_group, ())
                if isinstance(item, dict)
            )
            if active and not any(
                item.get("entity_type") == command.entity_type
                and item.get("entity_id") == command.entity_id
                for item in state.get("deletion_registry", ())
                if isinstance(item, dict)
            ):
                return MutationResult(state=state, mutation_kind=MutationKind.METADATA)
            updated = restore_entity(state, command.entity_type, command.entity_id)
            return MutationResult(
                state=updated,
                changed_ids=(command.entity_id,),
                invalidated_sections=("rflp", "mbse", "baseline", "project"),
                mutation_kind=MutationKind.HUMAN_CONTENT,
            )

        return coordinator.commit(
            mutation,
            expected_revision=expected_revision,
            expected_content_revision=snapshot.content_revision,
            event="entity.restored",
            audit_payload={
                "entity_type": command.entity_type,
                "entity_id": command.entity_id,
            },
        ).state


__all__ = [
    "DeleteEntityCommand",
    "DeleteEntityUseCase",
    "PreviewEntityDeletionCommand",
    "PreviewEntityDeletionUseCase",
    "RestoreEntityCommand",
    "RestoreEntityUseCase",
]
