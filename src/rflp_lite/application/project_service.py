"""Project creation and document ingestion use cases."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import shutil
from typing import Callable

from rflp_lite.application.workspaces import (
    WorkspaceRef,
    create_managed_workspace,
    list_managed_workspaces,
    managed_workspace,
)
from rflp_lite.domain.errors import ContractViolation, NotFoundError
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
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

    def delete(self, project_id: str) -> dict[str, str]:
        """Permanently remove one managed project workspace."""

        path = managed_workspace(self.workspace_root, project_id)
        raw_path = self.workspace_root / project_id
        if raw_path.is_symlink():
            raise ContractViolation("project workspace cannot be a symlink")
        if not path.is_dir():
            raise NotFoundError(f"project not found: {project_id}")
        shutil.rmtree(path)
        return {"project_id": project_id}

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

    def add_requirement(self, project_id: str, text: str) -> dict:
        clean = " ".join(str(text).split()).strip()
        if not clean:
            raise ContractViolation("requirement text is required")
        repository = self.repository(project_id)
        graph = repository.load_graph(project_id)
        entity = make_entity(
            EntityKind.REQUIREMENT,
            clean,
            {
                "statement": clean,
                "source": "user_input",
                "requires_human_review": True,
                "verification_method": "review",
            },
            status=EntityStatus.CANDIDATE,
            producer=Producer.USER,
            confidence=1.0,
            revision=graph.revision,
        )
        patch = Patch.create(
            project_id,
            "user.requirement_input",
            (AddEntity(entity),),
            "用户提交需求",
            graph.revision,
        )
        revision = repository.append_patch(project_id, patch, graph.revision)
        return {"requirement": entity.as_dict(), "revision": asdict(revision)}

    def has_analysis_input(self, project_id: str) -> bool:
        repository = self.repository(project_id)
        graph = repository.load_graph(project_id)
        if any(
            item.kind is EntityKind.REQUIREMENT
            and item.meta.status is not EntityStatus.DEPRECATED
            and item.meta.producer in {Producer.USER, Producer.IMPORT}
            for item in graph.entities
        ):
            return True
        checker = getattr(repository, "has_documents", None)
        return bool(checker(project_id)) if callable(checker) else False

    def ingest(self, project_id: str, document_path: Path) -> dict[str, object]:
        if document_path.suffix.casefold() == ".json":
            try:
                fixture = json.loads(document_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ContractViolation("JSON document cannot be read") from exc
            if isinstance(fixture, dict) and {"system", "stakeholders"} <= set(fixture):
                return self.seed_fixture(project_id, fixture, source_path=document_path)
        source = document_path.expanduser().resolve()
        if not source.is_file():
            raise NotFoundError(f"document not found: {source}")
        return self._save_parsed_document(project_id, source.name, source.read_bytes())

    def ingest_uploaded(self, project_id: str, filename: str, content: bytes) -> dict:
        safe_name = Path(str(filename or "upload")).name
        if not safe_name or safe_name in {".", ".."}:
            raise ContractViolation("uploaded filename is required")
        if not content:
            raise ContractViolation("uploaded document is empty")
        destination = self.path(project_id) / "inputs" / safe_name
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.suffix.casefold() == ".json":
            try:
                fixture = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ContractViolation("JSON document cannot be read") from exc
            if isinstance(fixture, dict) and {"system", "stakeholders"} <= set(fixture):
                destination.write_bytes(content)
                return self.seed_fixture(project_id, fixture, source_path=destination)

        destination.write_bytes(content)
        return self._save_parsed_document(project_id, safe_name, content)

    def _save_parsed_document(self, project_id: str, filename: str, content: bytes) -> dict:
        parsed = self.document_parser.parse(filename, content)
        repository = self.repository(project_id)
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

    def seed_fixture(
        self,
        project_id: str,
        fixture: dict[str, object],
        *,
        source_path: Path | None = None,
    ) -> dict[str, object]:
        """Import a deterministic fixture into the typed graph for offline E2E."""

        repository = self.repository(project_id)
        graph = repository.load_graph(project_id)
        operations: list[object] = []
        by_key: dict[tuple[EntityKind, str], str] = {}

        def add(kind: EntityKind, name: str, payload: dict[str, object] | None = None):
            clean = str(name).strip()
            if not clean or (kind, clean) in by_key:
                return None
            entity = make_entity(
                kind,
                clean,
                payload or {},
                status=EntityStatus.ACCEPTED,
                producer=Producer.IMPORT,
                confidence=1.0,
                revision=graph.revision,
            )
            if entity.id in graph.entity_index:
                by_key[(kind, clean)] = entity.id
                return entity.id
            by_key[(kind, clean)] = entity.id
            operations.append(AddEntity(entity))
            return entity.id

        system_id = add(EntityKind.SYSTEM, str(fixture.get("system", "")), {"fixture": True})
        stakeholder_ids = [add(EntityKind.STAKEHOLDER, str(item), {"fixture": True}) for item in fixture.get("stakeholders", ())]
        stage_ids = [add(EntityKind.LIFECYCLE_STAGE, str(item), {"fixture": True}) for item in fixture.get("lifecycle_stages", ())]
        scenario_ids = [add(EntityKind.SCENARIO_HYPOTHESIS, str(item), {"fixture": True}) for item in fixture.get("scenarios", ())]
        requirement_ids = []
        for item in fixture.get("requirements", ()):
            if isinstance(item, dict):
                requirement_ids.append(add(EntityKind.REQUIREMENT, str(item.get("statement", item.get("id", ""))), {"fixture_id": str(item.get("id", "")), "verification_method": str(item.get("verification_method", "review"))}))
        relation_ops: list[object] = []
        if system_id:
            relation_ops.extend(
                Relate(system_id, RelationPredicate.DECOMPOSES, target)
                for target in stakeholder_ids if target
            )
        for stakeholder_id in stakeholder_ids:
            for scenario_id in scenario_ids:
                if stakeholder_id and scenario_id:
                    relation_ops.append(Relate(stakeholder_id, RelationPredicate.DERIVED_FROM, scenario_id))
        for requirement_id in requirement_ids:
            for scenario_id in scenario_ids:
                if requirement_id and scenario_id:
                    relation_ops.append(Relate(requirement_id, RelationPredicate.DERIVED_FROM, scenario_id))
        operations.extend(relation_ops)
        if operations:
            patch = Patch.create(project_id, "import.fixture", tuple(operations), "导入 Golden fixture", graph.revision)
            repository.append_patch(project_id, patch, graph.revision)
        return {
            "document_id": f"fixture-{project_id}",
            "region_count": 0,
            "entity_count": len(operations) - len(relation_ops),
            "relation_count": len(relation_ops),
            "source_path": str(source_path) if source_path else "",
        }
