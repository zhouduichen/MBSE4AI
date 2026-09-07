"""Typed ModelGraph queries and guarded patch application."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph, Patch, Revision
from rflp_lite.repository.port import ModelRepository


class ModelService:
    def __init__(self, repository: ModelRepository):
        self.repository = repository

    def graph(self, project_id: str) -> ModelGraph:
        return self.repository.load_graph(project_id)

    def entities(self, project_id: str, kind: EntityKind | None = None):
        return self.repository.list_entities(project_id, kind)

    def apply_patch(self, project_id: str, patch: Patch, expected_revision: int) -> Revision:
        return self.repository.append_patch(project_id, patch, expected_revision)

    def issues(self, project_id: str):
        return self.repository.list_issues(project_id)
