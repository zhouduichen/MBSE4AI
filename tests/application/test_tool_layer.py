from rflp_lite.application.tool_layer import EngineeringToolLayer
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.retrieval.contracts import EvidenceCandidate
from rflp_lite.retrieval.evidence import EvidenceRetrievalResult


class _RetrievalTool:
    def retrieve(self, gap, context):
        assert gap.query
        assert context.task_id == "physical_candidates"
        return EvidenceRetrievalResult(candidates=(
            EvidenceCandidate(
                "region-1",
                "document_region",
                "doc-1",
                "page-1",
                "功耗要求",
                "系统功耗不得超过 50 W",
                0.95,
            ),
        ))

    @staticmethod
    def to_evidence(candidate):
        return {
            "id": f"evidence-{candidate.id}",
            "source_type": candidate.source_type,
            "source_id": candidate.source_id,
            "locator": candidate.locator,
            "claim": candidate.claim,
            "excerpt": candidate.excerpt,
            "relevance": candidate.confidence,
        }


def test_evidence_tool_persists_candidates_without_mutating_model_graph(tmp_path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    repository = services.repository("robot")
    graph = repository.load_graph("robot")
    tool = EngineeringToolLayer(repository, retrieval_engine=_RetrievalTool())

    result = tool.collect_evidence(
        "robot",
        graph,
        {
            "id": "controller-action-1",
            "task_id": "physical_candidates",
            "reason": "需要功耗证据",
            "entity_ids": [],
        },
    )

    assert result.status == "completed"
    assert result.evidence[0]["id"] == "evidence-region-1"
    assert repository.load_graph("robot").revision == graph.revision
    assert repository.list_evidence("robot")[0]["excerpt"] == "系统功耗不得超过 50 W"
