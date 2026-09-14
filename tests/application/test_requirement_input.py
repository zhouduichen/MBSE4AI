from pathlib import Path

from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.domain.entities import EntityKind
from rflp_lite.repository.sqlite import SQLiteModelRepository


def test_text_input_creates_deduplicated_requirements(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    service = RequirementInputService(repository, "p1")

    first = service.ensure_text_requirements("系统功耗不超过 50 W；系统应支持人工接管")
    second = service.ensure_text_requirements("系统功耗不超过 50 W；系统应支持人工接管")

    assert first == second
    assert len([item for item in repository.load_graph("p1").entities
                if item.kind is EntityKind.REQUIREMENT]) == 2


def test_document_input_preserves_region_source_id(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.save_document("p1", {"id": "doc-1", "kind": "pdf", "path": "input.pdf"})
    repository.save_source_regions(
        "p1",
        ({"id": "region-1", "document_id": "doc-1", "text": "系统应安全停机", "locator": "p1"},),
    )

    ids = RequirementInputService(repository, "p1").ensure_document_requirements(("doc-1",))

    requirement = repository.load_graph("p1").entity_index[ids[0]]
    assert requirement.meta.source_ids == ("region-1",)
    assert requirement.meta.evidence_ids == ("region-1",)
