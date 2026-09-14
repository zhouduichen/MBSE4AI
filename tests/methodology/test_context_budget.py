from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context_planner import HeuristicTokenEstimator
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import tasks_for_phase
from rflp_lite.retrieval.contracts import EvidenceCandidate
from rflp_lite.retrieval.evidence import EvidenceRetrievalResult


def test_heuristic_token_estimator_handles_chinese_and_english_deterministically():
    estimator = HeuristicTokenEstimator()

    assert estimator.estimate("需求 requirement") > 0
    assert estimator.estimate("需求 requirement") == estimator.estimate("需求 requirement")
    assert estimator.estimate("需求需求") > estimator.estimate("requirement")


def test_context_builder_uses_planned_relation_subset():
    task = tasks_for_phase(Phase.FUNCTIONAL)[0]
    graph = ModelGraph("p1", (make_entity(EntityKind.PHYSICAL_BLOCK, "物理"),))

    context = ContextBuilder().build(graph, task, token_budget=1)

    assert all(entity.kind is not EntityKind.PHYSICAL_BLOCK for entity in context.entities)
    assert all(relation.source_id in {entity.id for entity in context.entities} and relation.target_id in {entity.id for entity in context.entities} for relation in context.relations)


class _EvidenceRetriever:
    def retrieve(self, gap, context):
        del gap, context
        return EvidenceRetrievalResult(candidates=(
            EvidenceCandidate("e1", "document", "d1", "1", "短证据", "短证据"),
            EvidenceCandidate("e2", "document", "d2", "2", "更长证据", "更长证据" * 100),
        ))

    @staticmethod
    def to_evidence(candidate):
        return {"id": candidate.id, "claim": candidate.claim, "excerpt": candidate.excerpt}


def test_context_builder_keeps_graph_and_evidence_inside_shared_budget():
    task = tasks_for_phase(Phase.OPERATIONAL)[0]
    system = make_entity(EntityKind.SYSTEM, "系统")
    graph = ModelGraph("p1", (system,))

    context = ContextBuilder(_EvidenceRetriever()).build(
        graph, task, token_budget=100, output_reserve=40, prompt_reserve=20,
    )

    assert context.token_estimate <= 40
    assert len(context.evidence) <= 1


def test_context_builder_preserves_bound_evidence_before_retrieval_results():
    task = tasks_for_phase(Phase.OPERATIONAL)[0]
    graph = ModelGraph("p1", (make_entity(EntityKind.SYSTEM, "系统"),))
    baseline = {
        "id": "document-region-1",
        "source_type": "document_region",
        "source_id": "document-1",
        "locator": "page 1",
        "excerpt": "系统应支持人工接管",
    }

    context = ContextBuilder(_EvidenceRetriever()).build(
        graph,
        task,
        token_budget=200,
        output_reserve=40,
        prompt_reserve=20,
        evidence_bundle=(baseline,),
    )

    assert context.evidence
    assert context.evidence[0]["id"] == "document-region-1"
