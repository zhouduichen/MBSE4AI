"""Shared natural-language and document-region requirement input preparation."""

from __future__ import annotations

from collections.abc import Iterable

from rflp_lite.application.requirement_intake import (
    extract_requirement_constraints,
    split_requirement_statements,
)
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation, InputRequired
from rflp_lite.domain.model import AddEntity, Patch, UpdateEntity
from rflp_lite.repository.port import ModelRepository


class RequirementInputService:
    """Turn user/document text into idempotent USER requirement candidates."""

    def __init__(self, repository: ModelRepository, project_id: str):
        self.repository = repository
        self.project_id = str(project_id).strip()
        if not self.project_id:
            raise ContractViolation("project id is required")

    def ensure_text_requirements(self, text: str) -> tuple[str, ...]:
        if not split_requirement_statements(text):
            raise InputRequired("requirement text is required")
        return self.ensure(text=text)

    def ensure_document_requirements(
        self, document_ids: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        return self.ensure(document_ids=document_ids)

    def ensure(
        self,
        *,
        text: str | None = None,
        document_ids: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        """Ensure text and document statements share one input boundary."""

        candidates: list[tuple[str, tuple[str, ...]]] = []
        explicit_text = str(text or "").strip()
        if explicit_text:
            candidates.extend(
                (statement, ())
                for statement in split_requirement_statements(explicit_text)
            )
        if document_ids or not explicit_text:
            regions = self.repository.list_source_regions(self.project_id, document_ids)
            for region in regions:
                region_id = str(region.get("id", "")).strip()
                region_text = str(region.get("text", ""))
                if not region_id:
                    continue
                candidates.extend(
                    (statement, (region_id,))
                    for statement in split_requirement_statements(region_text)
                )
        if not candidates:
            raise InputRequired(
                "requirement text is required"
                if explicit_text or document_ids
                else "document input contains no readable requirement text"
            )
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
        operations: list[AddEntity | UpdateEntity] = []
        result: list[str] = []
        normalized: dict[str, list[str]] = {}
        for raw_statement, source_ids in candidates:
            statement = " ".join(str(raw_statement).split()).strip()
            if not statement:
                continue
            normalized.setdefault(statement, []).extend(
                str(source_id).strip()
                for source_id in source_ids
                if str(source_id).strip()
            )
        for statement, raw_source_ids in normalized.items():
            source_ids = tuple(dict.fromkeys(raw_source_ids))
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
                    evidence_ids=source_ids,
                    revision=graph.revision,
                )
                existing[statement] = entity
                operations.append(AddEntity(entity))
            else:
                merged_source_ids = tuple(
                    dict.fromkeys((*entity.meta.source_ids, *source_ids))
                )
                merged_evidence_ids = tuple(
                    dict.fromkeys((*entity.meta.evidence_ids, *source_ids))
                )
                if (
                    merged_source_ids != entity.meta.source_ids
                    or merged_evidence_ids != entity.meta.evidence_ids
                ):
                    operations.append(
                        UpdateEntity(
                            entity.id,
                            {
                                "source_ids": list(merged_source_ids),
                                "evidence_ids": list(merged_evidence_ids),
                            },
                        )
                    )
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
