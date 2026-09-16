from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.context_planner import ContextPlanner, HeuristicTokenEstimator
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import tasks_for_phase
from rflp_lite.methodology.vertical_generation import VerticalStage, stage_task
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


def test_vertical_functional_context_keeps_worklist_requirements_in_scope():
    requirements = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求-{index}")
        for index in range(2)
    )
    graph = ModelGraph("p1", requirements)
    context = ContextBuilder(
        planner=ContextPlanner(_FixedContextEstimator())
    ).build(
        graph,
        stage_task(VerticalStage.FUNCTIONAL),
        token_budget=20,
        output_reserve=0,
    )

    selected_ids = {item.id for item in context.entities}
    worklist = context.methodology_guidance["requirement_worklist"]
    assert selected_ids == {item.id for item in requirements}
    assert {
        item["requirement_id"] for item in worklist["items"]
    } == selected_ids


def test_vertical_worklist_reports_requirements_omitted_by_context_budget():
    requirements = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求-{index}")
        for index in range(5)
    )
    graph = ModelGraph("p1", requirements)
    context = ContextBuilder(
        planner=ContextPlanner(_FixedContextEstimator())
    ).build(
        graph,
        stage_task(VerticalStage.FUNCTIONAL),
        token_budget=20,
        output_reserve=0,
    )

    worklist = context.methodology_guidance["requirement_worklist"]
    selected_ids = {item.id for item in context.entities}
    assert context.token_estimate <= 20
    assert selected_ids == {
        item["requirement_id"] for item in worklist["items"]
    }
    assert worklist["truncated"] is True
    assert set(worklist["omitted_requirement_ids"]) == {
        item.id for item in requirements
    } - selected_ids


def test_vertical_physical_context_keeps_all_worklist_requirements_before_batch_scoping():
    requirements = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求-{index}")
        for index in range(5)
    )
    functions = tuple(
        make_entity(EntityKind.FUNCTION, f"功能-{index}")
        for index in range(5)
    )
    logicals = tuple(
        make_entity(EntityKind.LOGICAL_COMPONENT, f"逻辑-{index}")
        for index in range(5)
    )
    graph = ModelGraph("p1", (*requirements, *functions, *logicals))

    context = ContextBuilder().build(
        graph,
        stage_task(VerticalStage.PHYSICAL),
        token_budget=16384,
        output_reserve=4096,
        prompt_reserve=256,
    )

    worklist = context.methodology_guidance["requirement_worklist"]
    assert len(worklist["items"]) == len(requirements)
    assert worklist["truncated"] is False


def test_vertical_worklist_marks_current_targets_outside_context():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "需求",
        {"statement": "系统应自主配送"},
    )
    function = make_entity(
        EntityKind.FUNCTION,
        "配送功能",
        status=EntityStatus.VALIDATED,
    )
    graph = ModelGraph(
        "p1",
        (requirement, function),
        (
            Relation(
                "r-f",
                requirement.id,
                RelationPredicate.SATISFIED_BY,
                function.id,
            ),
        ),
    )

    context = ContextBuilder(
        planner=ContextPlanner(_FixedContextEstimator())
    ).build(
        graph,
        stage_task(VerticalStage.FUNCTIONAL),
        root_entity_ids=(requirement.id,),
        token_budget=10,
        output_reserve=0,
    )

    item = context.methodology_guidance["requirement_worklist"]["items"][0]
    assert {entity.id for entity in context.entities} == {requirement.id}
    assert item["current"]["function_ids"] == [function.id]
    assert item["available_current"]["function_ids"] == []
    assert item["unavailable_current"]["function_ids"] == [function.id]


def test_assurance_context_preserves_complete_rflp_scope_for_vv_tasks():
    requirement = make_entity(EntityKind.REQUIREMENT, "需求")
    function = make_entity(EntityKind.FUNCTION, "功能")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "逻辑")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "物理")
    graph = ModelGraph(
        "p1",
        (requirement, function, logical, physical),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        ),
    )
    task = next(item for item in tasks_for_phase(Phase.ASSURANCE) if item.id == "verification_validation")

    context = ContextBuilder().build(graph, task, token_budget=10000)

    assert {item.kind for item in context.entities} == {
        EntityKind.REQUIREMENT,
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
    }
    assert len(context.relations) == 3


class _FixedContextEstimator:
    def estimate(self, value):
        return 10 if isinstance(value, dict) and "kind" in value else 1


def test_assurance_context_is_budgeted_and_reports_omissions():
    requirements = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求-{index}")
        for index in range(2)
    )
    functions = tuple(
        make_entity(EntityKind.FUNCTION, f"功能-{index}")
        for index in range(2)
    )
    logicals = tuple(
        make_entity(EntityKind.LOGICAL_COMPONENT, f"逻辑-{index}")
        for index in range(2)
    )
    graph = ModelGraph(
        "p1",
        (*requirements, *functions, *logicals),
        (
            Relation("r0-f0", requirements[0].id, RelationPredicate.SATISFIED_BY, functions[0].id),
            Relation("f0-l0", functions[0].id, RelationPredicate.ALLOCATED_TO, logicals[0].id),
            Relation("r1-f1", requirements[1].id, RelationPredicate.SATISFIED_BY, functions[1].id),
            Relation("f1-l1", functions[1].id, RelationPredicate.ALLOCATED_TO, logicals[1].id),
        ),
    )
    task = next(
        item for item in tasks_for_phase(Phase.ASSURANCE)
        if item.id == "verification_validation"
    )

    context = ContextBuilder(
        planner=ContextPlanner(_FixedContextEstimator())
    ).build(graph, task, token_budget=20, output_reserve=0)

    selected_ids = {item.id for item in context.entities}
    guidance = context.methodology_guidance["context_selection"]
    assert context.token_estimate <= 20
    assert selected_ids == {requirements[0].id, requirements[1].id}
    assert set(guidance["selected_requirement_ids"]) == {
        requirements[0].id, requirements[1].id,
    }
    assert set(guidance["omitted_entity_ids"]) == {
        functions[0].id, functions[1].id, logicals[0].id, logicals[1].id,
    }
    assert guidance["available_budget"] == 20
    assert all(
        relation.source_id in selected_ids and relation.target_id in selected_ids
        for relation in context.relations
    )


def test_vertical_assurance_context_preserves_existing_vv_scope_during_reanalysis():
    requirement = make_entity(EntityKind.REQUIREMENT, "需求")
    function = make_entity(EntityKind.FUNCTION, "功能")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "逻辑")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "物理")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证")
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认")
    graph = ModelGraph(
        "p1",
        (requirement, function, logical, physical, verification, validation),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
            Relation("r-va", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
        ),
    )
    context = ContextBuilder().build(
        graph,
        stage_task(VerticalStage.VERIFICATION_VALIDATION),
        token_budget=10000,
    )

    assert {item.kind for item in context.entities} == {
        EntityKind.REQUIREMENT,
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    }
    assert len(context.relations) == 5


def test_full_graph_context_keeps_all_assurance_endpoints_without_budget_projection():
    requirement = make_entity(EntityKind.REQUIREMENT, "需求")
    function = make_entity(EntityKind.FUNCTION, "功能")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "逻辑")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "物理")
    graph = ModelGraph(
        "p1",
        (requirement, function, logical, physical),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        ),
    )
    task = stage_task(VerticalStage.VERIFICATION_VALIDATION)

    context = ContextBuilder().build(
        graph,
        task,
        token_budget=1,
        output_reserve=0,
        full_graph=True,
    )

    assert {item.id for item in context.entities} == {
        requirement.id, function.id, logical.id, physical.id,
    }
    assert len(context.relations) == 3


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
