from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_persistence import enrich_vertical_patch
from rflp_lite.methodology.completion import evaluate_vertical_stage


def _patch(project_id, task_id, operations=()):
    return Patch.create(project_id, task_id, tuple(operations), "test closure", 0)


def _base_rflp_graph():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统必须完成任务",
        {"functional_behavior_ids": ["pending"]},
    )
    function = make_entity(
        EntityKind.FUNCTION,
        "执行任务",
        {"decomposition": "接收输入并完成任务"},
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "任务控制器",
        {"function_id": function.id, "responsibility": "控制任务执行"},
    )
    graph = ModelGraph("p1", (requirement, function, logical))
    return graph, requirement, function, logical


def test_logical_closure_materializes_allocation_interface_and_state():
    graph, requirement, function, logical = _base_rflp_graph()

    graph = apply_patch(
        graph,
        _patch(
            "p1",
            "seed",
            (
                Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            ),
        ),
    )
    enriched = enrich_vertical_patch(
        graph,
        Patch.create("p1", "vertical.logical", (), "logical closure", graph.revision),
    )
    result = apply_patch(graph, enriched)

    assert any(
        item.source_id == function.id
        and item.predicate is RelationPredicate.ALLOCATED_TO
        and item.target_id == logical.id
        for item in result.relations
    )
    assert any(item.kind is EntityKind.INTERFACE for item in result.entities)
    assert any(item.kind is EntityKind.STATE for item in result.entities)
    checks = {str(item["id"]): item["passed"] for item in evaluate_vertical_stage("logical", result).checks}
    assert checks["logical_analysis"]
    assert checks["dependency_clustering"]
    assert checks["interface_sequence_state"]


def test_functional_closure_reifies_non_function_flow_endpoint():
    graph, requirement, function, _logical = _base_rflp_graph()
    flow = make_entity(
        EntityKind.FUNCTIONAL_FLOW,
        "外部配送任务流",
        {
            "source_function_ids": [requirement.id],
            "target_function_ids": [function.id],
        },
    )
    patch = Patch.create(
        "p1",
        "vertical.functional",
        (AddEntity(flow),),
        "functional closure",
        graph.revision,
    )
    result = apply_patch(graph, enrich_vertical_patch(graph, patch))
    adapters = [
        item
        for item in result.entities
        if item.kind is EntityKind.FUNCTION
        and item.payload.get("flow_id") == flow.id
    ]
    assert adapters
    repaired_flow = result.entity_index[flow.id]
    assert repaired_flow.payload["source_function_ids"] == [adapters[0].id]
    assert any(
        item.source_id == adapters[0].id
        and item.predicate is RelationPredicate.EXCHANGES_WITH
        and item.target_id == flow.id
        for item in result.relations
    )


def test_physical_closure_recovers_typed_trace_from_payload_references():
    graph, requirement, function, logical = _base_rflp_graph()

    graph = apply_patch(
        graph,
        _patch(
            "p1",
            "seed",
            (
                Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
                Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            ),
        ),
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "候选执行平台",
        {
            "candidate_type": "edge-compute",
            "selection_rationale": "满足计算需求",
            "source_requirement_ids": [requirement.id],
            "source_logical_ids": [logical.id],
            "impact_chain": {"requirement_ids": [requirement.id]},
        },
    )
    patch = Patch.create(
        "p1",
        "vertical.physical",
        (AddEntity(physical),),
        "physical closure",
        graph.revision,
    )
    enriched = enrich_vertical_patch(graph, patch)
    result = apply_patch(graph, enriched)
    assert any(
        item.source_id == requirement.id
        and item.predicate is RelationPredicate.SATISFIED_BY
        and item.target_id == physical.id
        for item in result.relations
    )
    assert any(
        item.source_id == logical.id
        and item.predicate is RelationPredicate.ALLOCATED_TO
        and item.target_id == physical.id
        for item in result.relations
    )


def test_assurance_closure_keeps_risk_candidates_reviewable_and_checks_vv_scope():
    graph, requirement, _function, _logical = _base_rflp_graph()
    verification_payload = {
        "method": "simulation",
        "verification_objective": "验证需求",
        "precondition": "系统可运行",
        "test_condition": "正常输入",
        "input": "输入样例",
        "stimulus": "启动任务",
        "procedure": "执行并记录结果",
        "expected_result": "任务完成",
        "pass_criteria": "结果满足需求",
        "requirement_ids": [requirement.id],
    }
    validation_payload = {
        **verification_payload,
        "method": "field_test",
    }
    verification = make_entity(EntityKind.VERIFICATION_CASE, "需求验证", verification_payload)
    validation = make_entity(EntityKind.VALIDATION_CASE, "需求确认", validation_payload)
    patch = Patch.create(
        "p1",
        "vertical.verification_validation",
        (AddEntity(verification), AddEntity(validation)),
        "assurance closure",
        graph.revision,
    )
    enriched = enrich_vertical_patch(graph, patch)
    result = apply_patch(graph, enriched)

    failure_modes = [item for item in result.entities if item.kind is EntityKind.FAILURE_MODE]
    assert failure_modes
    assert all(item.meta.producer.value == "rule" for item in failure_modes)
    assert any(
        item.predicate is RelationPredicate.CAUSES
        and item.source_id.startswith("hazard-")
        and item.target_id.startswith("failure_mode-")
        for item in result.relations
    )
    persisted_verification = result.entity_index[verification.id]
    assert persisted_verification.payload["cross_analysis_status"] == "checked"
    checks = {str(item["id"]): item["passed"] for item in evaluate_vertical_stage("verification_validation", result).checks}
    assert checks["fmea_stpa_hazard"]
    assert checks["verification_validation"]
    assert checks["global_cross_analysis"]
