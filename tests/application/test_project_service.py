from pathlib import Path

import pytest

from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.application.project_service import ProjectService
from rflp_lite.application.workspaces import create_managed_workspace
from rflp_lite.domain.errors import ContractViolation, NotFoundError
from rflp_lite.repository.sqlite import SQLiteModelRepository


def _service(root: Path) -> ProjectService:
    return ProjectService(root, SQLiteModelRepository, LocalDocumentParser())


def test_delete_removes_a_managed_project_tree(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = create_managed_workspace(root, "p1")
    (project.path / ".rflp").mkdir()
    (project.path / ".rflp" / "model.db").write_bytes(b"db")
    (project.path / "inputs").mkdir()
    (project.path / "inputs" / "requirements.txt").write_text("requirement", encoding="utf-8")

    result = _service(root).delete("p1")

    assert result == {"project_id": "p1"}
    assert not project.path.exists()


def test_delete_rejects_invalid_and_missing_projects(tmp_path: Path) -> None:
    service = _service(tmp_path / "workspaces")

    with pytest.raises(ContractViolation):
        service.delete("../outside")
    with pytest.raises(NotFoundError):
        service.delete("missing")


def test_delete_rejects_symlinked_project_targets(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContractViolation):
        _service(root).delete("linked")
    assert outside.exists()


def test_add_requirement_creates_user_candidate_and_counts_as_analysis_input(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")
    service = _service(root)

    result = service.add_requirement("p1", "系统应在断网后继续安全运行")

    assert result["requirement"]["name"] == "系统应在断网后继续安全运行"
    assert result["requirement"]["producer"] == "user"
    assert result["requirement"]["status"] == "candidate"
    assert result["revision"]["sequence"] == 1
    assert service.has_analysis_input("p1") is True


def test_add_requirement_rejects_blank_text(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")

    with pytest.raises(ContractViolation, match="requirement text is required"):
        _service(root).add_requirement("p1", "  ")


def test_uploaded_text_document_is_saved_and_counts_as_analysis_input(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = create_managed_workspace(root, "p1")
    service = _service(root)

    result = service.ingest_uploaded("p1", "requirements.txt", "系统应支持人工接管\n".encode())

    assert result["region_count"] == 1
    assert (project.path / "inputs" / "requirements.txt").read_text(encoding="utf-8") == "系统应支持人工接管\n"
    assert service.has_analysis_input("p1") is True


def test_uploaded_empty_document_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")

    with pytest.raises(ContractViolation, match="uploaded document is empty"):
        _service(root).ingest_uploaded("p1", "empty.txt", b"")
