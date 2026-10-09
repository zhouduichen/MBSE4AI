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


def test_combined_input_merges_document_provenance_without_duplicate_requirement(
    tmp_path: Path,
):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.save_document("p1", {"id": "doc-1", "kind": "txt", "path": "input.txt"})
    repository.save_source_regions(
        "p1",
        (
            {"id": "region-1", "document_id": "doc-1", "text": "系统应安全停机", "locator": "p1"},
            {"id": "region-2", "document_id": "doc-1", "text": "系统应安全停机", "locator": "p2"},
        ),
    )
    service = RequirementInputService(repository, "p1")

    ids = service.ensure(text="系统应安全停机", document_ids=("doc-1",))
    first_revision = repository.load_graph("p1").revision
    repeated = service.ensure(text="系统应安全停机", document_ids=("doc-1",))
    graph = repository.load_graph("p1")
    requirement = graph.entity_index[ids[0]]

    assert repeated == ids
    assert graph.revision == first_revision
    assert requirement.meta.source_ids == ("region-1", "region-2")
    assert requirement.meta.evidence_ids == ("region-1", "region-2")
    assert len([item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]) == 1


def test_text_and_document_inputs_keep_independent_requirements(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.save_document("p1", {"id": "doc-1", "kind": "txt", "path": "input.txt"})
    repository.save_source_regions(
        "p1",
        ({"id": "region-1", "document_id": "doc-1", "text": "系统应支持人工接管", "locator": "p1"},),
    )

    ids = RequirementInputService(repository, "p1").ensure(
        text="系统应自主配送", document_ids=("doc-1",)
    )
    graph = repository.load_graph("p1")

    assert len(ids) == 2
    assert len([item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]) == 2
    names = {graph.entity_index[item].meta.name for item in ids}
    assert names == {"系统应自主配送", "系统应支持人工接管"}
