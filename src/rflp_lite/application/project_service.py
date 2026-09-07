"""Project creation and document ingestion use cases."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Callable

from rflp_lite.application.workspaces import (
    WorkspaceRef,
    create_managed_workspace,
    list_managed_workspaces,
    managed_workspace,
)
from rflp_lite.domain.errors import ContractViolation, NotFoundError
from rflp_lite.ports.document_intelligence import DocumentParserPort
from rflp_lite.repository.port import ModelRepository


class ProjectService:
    """Own project paths and convert parsed documents into source regions."""

    def __init__(
        self,
        workspace_root: Path,
        repository_factory: Callable[[Path], ModelRepository],
        document_parser: DocumentParserPort,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.repository_factory = repository_factory
        self.document_parser = document_parser

    def path(self, project_id: str) -> Path:
        candidate = managed_workspace(self.workspace_root, project_id)
        if not candidate.is_dir():
            raise NotFoundError(f"project not found: {project_id}")
        return candidate

    def repository(self, project_id: str) -> ModelRepository:
        path = self.path(project_id)
        repository = self.repository_factory(path / ".rflp" / "model.db")
        repository.ensure_project(project_id, project_id)
        return repository

    def list(self) -> tuple[WorkspaceRef, ...]:
        return list_managed_workspaces(self.workspace_root)

    def create(self, project_id: str, name: str = "") -> dict[str, object]:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        path = managed_workspace(self.workspace_root, project_id)
        if path.exists():
            raise ContractViolation(f"project already exists: {project_id}")
        workspace = create_managed_workspace(self.workspace_root, project_id)
        repository = self.repository_factory(path / ".rflp" / "model.db")
        repository.ensure_project(project_id, name.strip() or project_id)
        return {"id": project_id, "name": name.strip() or project_id, "path": str(workspace.path)}

    def summary(self, project_id: str) -> dict[str, object]:
        repository = self.repository(project_id)
        graph = repository.load_graph(project_id)
        return {
            "id": project_id,
            "path": str(self.path(project_id)),
            "revision": graph.revision,
            "entity_count": len(graph.entities),
            "relation_count": len(graph.relations),
            "evidence_count": len(repository.list_evidence(project_id)),
        }

    def ingest(self, project_id: str, document_path: Path) -> dict[str, object]:
        repository = self.repository(project_id)
        source = document_path.expanduser().resolve()
        if not source.is_file():
            raise NotFoundError(f"document not found: {source}")
        parsed = self.document_parser.parse(source.name, source.read_bytes())
        repository.save_document(
            project_id,
            {
                "id": parsed.artifact.id,
                "kind": parsed.artifact.kind,
                "path": parsed.artifact.path,
                "name": parsed.artifact.path,
                "sha256": parsed.artifact.sha256,
            },
        )
        repository.save_source_regions(
            project_id,
            tuple(
                {
                    "id": region.id,
                    "document_id": region.artifact_id,
                    "page": region.page,
                    "locator": region.locator,
                    "text": region.text,
                    "bbox": list(region.bbox),
                    "heading_path": list(region.heading_path),
                }
                for region in parsed.regions
            ),
        )
        return {
            "document_id": parsed.artifact.id,
            "name": parsed.artifact.path,
            "region_count": len(parsed.regions),
            "diagnostics": [asdict(item) for item in parsed.diagnostics],
        }
