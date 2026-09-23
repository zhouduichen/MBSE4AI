from pathlib import Path

from rflp_lite.application.workspaces import create_managed_workspace
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import tasks_for_phase
from rflp_lite.retrieval.planner import KnowledgeGap, RetrievalTask
from rflp_lite.retrieval.history import HistoricalProjectRetriever
from rflp_lite.repository.sqlite import SQLiteModelRepository


def test_historical_retriever_reads_other_managed_projects(tmp_path: Path):
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "current")
    create_managed_workspace(root, "archive")
    archive_path = root / "archive" / ".rflp" / "model.db"
    archive = SQLiteModelRepository(archive_path)
    archive.ensure_project("archive")
    archive.save_document("archive", {"id": "doc-1", "kind": "txt", "path": "history.txt"})
    archive.save_source_regions(
        "archive",
        [{"id": "region-1", "document_id": "doc-1", "text": "历史项目采用人工接管策略", "locator": "p1"}],
    )

    current = SQLiteModelRepository(root / "current" / ".rflp" / "model.db")
    current.ensure_project("current")
    retriever = HistoricalProjectRetriever(
        current,
        project_sources=(("archive", archive_path),),
        repository_factory=SQLiteModelRepository,
    )
    candidates = retriever.search(
        RetrievalTask("gap", "人工接管", "historical_projects", "current", "hash"),
    )

    assert candidates
    assert candidates[0].source_type == "historical_project"
    assert candidates[0].source_id.startswith("archive:")
    assert candidates[0].locator.startswith("archive:")


def test_v2_evidence_service_wires_cross_project_history(tmp_path: Path):
    root = tmp_path / "workspaces"
    services = build_v2_services(root)
    services.projects.create("current")
    services.projects.create("archive")
    archive = services.repository("archive")
    archive.save_document("archive", {"id": "doc-1", "kind": "txt", "path": "history.txt"})
    archive.save_source_regions(
        "archive",
        [{"id": "region-1", "document_id": "doc-1", "text": "历史项目采用人工接管策略", "locator": "p1"}],
    )
    repository = services.repository("current")
    context = ContextBuilder().build(
        repository.load_graph("current"), tasks_for_phase(Phase.OPERATIONAL)[0]
    )

    result = services.evidence("current").search(
        KnowledgeGap("history", "人工接管"),
        context,
    )

    assert any(item.source_type == "historical_project" for item in result.candidates)
    assert any(item["source_type"] == "historical_project" for item in repository.list_evidence("current"))
