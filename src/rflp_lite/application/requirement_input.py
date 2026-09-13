"""Shared natural-language and document-region requirement input preparation."""

from __future__ import annotations

from collections.abc import Iterable

from rflp_lite.application.requirement_intake import (
    extract_requirement_constraints,
    split_requirement_statements,
)
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation, InputRequired
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.repository.port import ModelRepository


class RequirementInputService:
    """Turn user/document text into idempotent USER requirement candidates."""

    def __init__(self, repository: ModelRepository, project_id: str):
        self.repository = repository
        self.project_id = str(project_id).strip()
        if not self.project_id:
            raise ContractViolation("project id is required")

    def ensure_text_requirements(self, text: str) -> tuple[str, ...]:
        statements = split_requirement_statements(text)
        if not statements:
            raise InputRequired("requirement text is required")
        return self._ensure_statements((statement, ()) for statement in statements)

    def ensure_document_requirements(
        self, document_ids: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        regions = self.repository.list_source_regions(self.project_id, document_ids)
        candidates: list[tuple[str, tuple[str, ...]]] = []
        for region in regions:
            region_id = str(region.get("id", "")).strip()
            text = str(region.get("text", ""))
            if not region_id:
                continue
            candidates.extend((statement, (region_id,)) for statement in split_requirement_statements(text))
        if not candidates:
            raise InputRequired("document input contains no readable requirement text")
        return self._ensure_statements(candidates)

    def _ensure_statements(
        self, candidates: Iterable[tuple[str, tuple[str, ...]]]
    ) -> tuple[str, ...]:
        graph = self.repository.load_graph(self.project_id)
        existing = {
            str(entity.payload.get("statement", entity.meta.name)).strip(): entity
            for entity in graph.entities
            if entity.kind is EntityKind.REQUIREMENT
            and entity.meta.status is not EntityStatus.DEPRECATED
        }
        operations: list[AddEntity] = []
        result: list[str] = []
        for raw_statement, source_ids in candidates:
            statement = " ".join(str(raw_statement).split()).strip()
            if not statement:
                continue
            entity = existing.get(statement)
            if entity is None:
                payload: dict[str, object] = {
                    "statement": statement,
                    "source": "user_input" if not source_ids else "document_region",
                    "requires_human_review": True,
                    "level": "system",
                    "type": "functional",
                    "obligation": "系统应",
                    "verification_method": "test",
                }
                payload.update(extract_requirement_constraints(statement))
                entity = make_entity(
                    EntityKind.REQUIREMENT,
                    statement,
                    payload,
                    status=EntityStatus.CANDIDATE,
                    producer=Producer.USER,
                    confidence=1.0,
                    source_ids=source_ids,
                    revision=graph.revision,
                )
                existing[statement] = entity
                operations.append(AddEntity(entity))
            result.append(entity.id)
        if not result:
            raise InputRequired("requirement input contains no readable statements")
        if operations:
            patch = Patch.create(
                self.project_id,
                "user.requirement_input",
                tuple(operations),
                "用户/文档输入需求",
                graph.revision,
            )
            self.repository.append_patch(self.project_id, patch, graph.revision)
        return tuple(result)


__all__ = ["RequirementInputService"]
