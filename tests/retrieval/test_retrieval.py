from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import tasks_for_phase
from rflp_lite.retrieval.planner import KnowledgeGap


def test_local_retrieval_and_missing_web_are_non_blocking(tmp_path):
    services = build_v2_services(tmp_path)
    services.projects.create("p1")
    repo = services.repository("p1")
    repo.save_document("p1", {"id": "doc-1", "kind": "txt", "path": "a.txt", "sha256": "x"})
    repo.save_source_regions("p1", [{"id": "region-1", "document_id": "doc-1", "text": "通信丢失恢复", "locator": "p1"}])
    context = ContextBuilder().build(repo.load_graph("p1"), tasks_for_phase(Phase.OPERATIONAL)[0])

    result = services.evidence("p1").search(KnowledgeGap("communication", "通信丢失恢复"), context)

    assert result.workflow_blocked is False
    assert any(item.source_type == "source_region" for item in result.candidates)
    assert any(item.code == "external_evidence_gap" for item in result.gaps)
