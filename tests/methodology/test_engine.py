from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.engine import MethodologyEngine
from rflp_lite.methodology.trace_rules import requirement_trace_scope


def _graph(
    *,
    power_w: float | None = 40,
    max_power_w: float | None = None,
    endurance_h: float | None = None,
    min_endurance_h: float | None = None,
    complete_vv: bool = False,
) -> ModelGraph:
    requirement_payload = {"statement": "系统应在任务期间保持可用"}
    if max_power_w is not None:
        requirement_payload["constraints"] = {"max_power_w": max_power_w}
    if min_endurance_h is not None:
        requirement_payload.setdefault("constraints", {})["min_endurance_h"] = min_endurance_h
    requirement = make_entity(EntityKind.REQUIREMENT, "任务可用性", requirement_payload)
    function = make_entity(
        EntityKind.FUNCTION,
        "执行任务",
        {"dependencies": [], "shared_state": ["task_state"]},
        status=EntityStatus.VALIDATED,
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "任务控制器",
        {
            "partition_basis": "共享任务状态和时序依赖",
            "dependencies": [function.id],
            "shared_state": ["task_state"],
            "timing_constraints": ["状态更新有序"],
            "safety_isolation": ["接管路径隔离"],
            "cohesion": "high",
            "coupling": "controlled",
        },
        status=EntityStatus.VALIDATED,
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "任务计算平台",
        {
            "mass_kg": 1.0,
            "power_w": power_w,
            "compute": 100,
            "memory_mb": 512,
            "latency_ms": 20,
            "bandwidth_mbps": 100,
            "cost": 1000,
            "thermal": "可控",
            "reliability": "待试验",
            "availability": "待运行数据",
            "endurance_h": endurance_h,
            "swap_c": {"mass_kg": 1.0, "power_w": power_w, "cost": 1000},
            "feasibility": {"status": "candidate"},
        },
        status=EntityStatus.VALIDATED,
    )
    verification_payload = {
        "method": "test",
        "verification_objective": "证明任务可用性需求满足",
        "precondition": "设备上电",
        "test_condition": "标准运行环境和需求边界条件",
        "input": "配送任务",
        "stimulus": "提交配送任务并触发运行事件",
        "procedure": "执行任务并采集结果",
        "expected_result": "任务完成",
        "pass_criteria": "结果满足需求",
        "evidence_ids": ["evidence-1"],
        "execution_evidence_ids": ["execution-1"],
    }
    validation_payload = {
        "method": "demonstration",
        "verification_objective": "确认任务场景目标达成",
        "precondition": "用户在场",
        "test_condition": "典型用户和代表性任务条件",
        "input": "配送任务",
        "stimulus": "用户执行配送操作",
        "procedure": "用户观察执行",
        "expected_result": "用户认可结果",
        "pass_criteria": "场景目标达成",
        "evidence_ids": ["evidence-2"],
        "execution_evidence_ids": ["execution-2"],
    }
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证任务可用性",
        verification_payload if complete_vv else {"method": "test", "pass_criteria": "满足需求"},
        status=EntityStatus.VALIDATED,
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "确认任务体验",
        validation_payload if complete_vv else {"method": "demonstration", "pass_criteria": "用户认可"},
        status=EntityStatus.VALIDATED,
    )
    entities = (requirement, function, logical, physical, verification, validation)
    relations = (
        Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relation("r-va", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    )
    return ModelGraph("p1", entities, relations, revision=1)


def test_logical_analysis_reports_partition_quality_and_allocation():
    report = MethodologyEngine().analyze(_graph())

    assert report.metrics["logical_allocation_coverage"] == 1.0
    assert report.metrics["logical_partition_count"] == 1
    assert report.metrics["logical_cross_component_exchange_count"] == 0
    assert {item["step"] for item in report.decisions} >= {
        "dependency_clustering", "architecture_evaluation"
    }
    assert not any(item.code == "logical_function_unallocated" for item in report.findings)


def test_operational_and_functional_analysis_reports_missing_context():
    report = MethodologyEngine().analyze(_graph())

    assert report.metrics["operational_context_coverage"] < 1.0
    assert any(item.code == "operational_activity_missing" for item in report.findings)
    assert report.metrics["functional_requirement_coverage"] == 1.0
    assert report.metrics["functional_flow_coverage"] == 0.0
    assert report.metrics["functional_decomposition_coverage"] == 0.0
    assert any(item.code == "functional_flow_missing" for item in report.findings)
    assert any(item.code == "functional_decomposition_missing" for item in report.findings)


def test_physical_analysis_distinguishes_conflict_from_unknown_measurement():
    conflict = MethodologyEngine().analyze(_graph(power_w=80, max_power_w=50))
    unknown = MethodologyEngine().analyze(_graph(power_w=None, max_power_w=50))

    assert any(item.code == "physical_constraint_conflict" for item in conflict.findings)
    assert conflict.metrics["physical_feasibility"] == "infeasible"
    assert any(item.code == "physical_measurement_required" for item in unknown.findings)
    assert unknown.metrics["physical_feasibility"] == "needs_measurement"


def test_physical_analysis_checks_endurance_constraint():
    report = MethodologyEngine().analyze(_graph(endurance_h=8, min_endurance_h=10))

    assert any(
        item.code == "physical_constraint_conflict" and "endurance_h" in item.message
        for item in report.findings
    )
    assert report.metrics["physical_feasibility"] == "infeasible"


def test_vv_analysis_requires_structured_verification_and_validation():
    report = MethodologyEngine().analyze(_graph(complete_vv=False))

    assert report.metrics["verification_coverage"] == 1.0
    assert report.metrics["validation_coverage"] == 1.0
    assert report.metrics["structured_verification_coverage"] == 0.0
    assert report.metrics["structured_validation_coverage"] == 0.0
    assert any(item.code == "verification_case_incomplete" for item in report.findings)
    assert any(item.code == "validation_case_incomplete" for item in report.findings)


def test_vv_plan_and_execution_evidence_are_reported_separately():
    report = MethodologyEngine().analyze(_graph(complete_vv=True))

    assert report.metrics["structured_verification_coverage"] == 1.0
    assert report.metrics["structured_validation_coverage"] == 1.0
    assert report.metrics["verification_evidence_coverage"] == 1.0
    assert report.metrics["validation_evidence_coverage"] == 1.0
    assert not any(item.code == "verification_case_incomplete" for item in report.findings)


def test_source_evidence_does_not_count_as_vv_execution_evidence():
    graph = _graph(complete_vv=True)
    entities = tuple(
        item.__class__(item.meta, {**item.payload, "execution_evidence_ids": []})
        if item.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
        else item
        for item in graph.entities
    )

    report = MethodologyEngine().analyze(
        ModelGraph(graph.project_id, entities, graph.relations, graph.revision)
    )

    assert report.metrics["verification_evidence_coverage"] == 0.0
    assert report.metrics["validation_evidence_coverage"] == 0.0
    assert any(item.code == "verification_evidence_missing" for item in report.findings)
    assert any(item.code == "validation_evidence_missing" for item in report.findings)


def test_vv_scope_consistency_detects_stale_case_payload():
    graph = _graph(complete_vv=True)
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    scope = requirement_trace_scope(graph, requirement.id).as_dict()
    entities = tuple(
        item.__class__(item.meta, {**item.payload, **scope, "cross_analysis_status": "checked"})
        if item.kind is EntityKind.VERIFICATION_CASE
        else item.__class__(item.meta, {**item.payload, **scope})
        if item.kind is EntityKind.VALIDATION_CASE
        else item
        for item in graph.entities
    )
    scoped = ModelGraph(graph.project_id, entities, graph.relations, graph.revision)
    verification = next(item for item in entities if item.kind is EntityKind.VERIFICATION_CASE)
    stale_entities = tuple(
        item.__class__(item.meta, {**item.payload, "physical_ids": []})
        if item.id == verification.id else item
        for item in entities
    )
    stale = ModelGraph(graph.project_id, stale_entities, graph.relations, graph.revision)

    report = MethodologyEngine().analyze(stale)

    assert MethodologyEngine().analyze(scoped).metrics["vv_scope_consistency"] == 1.0
    assert report.metrics["vv_scope_consistency"] == 0.5
    assert report.metrics["vv_scope_mismatch_count"] == 1
    assert any(
        item.code == "vv_scope_mismatch" and verification.id in item.entity_ids
        for item in report.findings
    )


def test_impact_analysis_walks_graph_and_routes_concrete_tasks():
    graph = _graph(complete_vv=True)
    requirement_id = next(item.id for item in graph.entities if item.kind is EntityKind.REQUIREMENT)

    report = MethodologyEngine().analyze(graph, changed_entity_ids=(requirement_id,))

    impacted = set(report.impacted_entity_ids)
    assert impacted == {item.id for item in graph.entities}
    assert {"requirements", "functional", "logical", "physical", "assurance"} <= set(report.impacted_stages)
    assert {
        "system_requirement_derivation",
        "function_identification",
        "logical_analysis",
        "physical_candidates",
        "verification_validation",
    } <= set(report.recommended_tasks)
    assert any(path[0] == requirement_id and len(path) >= 2 for path in report.impact_paths)


def test_technical_requirements_are_vv_inputs_but_not_functional_inputs():
    graph = _graph(complete_vv=True)
    root = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    technical = make_entity(
        EntityKind.REQUIREMENT,
        "物理功耗技术约束",
        {"level": "technical", "constraints": {"max_power_w": 50}},
    )
    graph = ModelGraph(
        graph.project_id,
        (*graph.entities, technical),
        (
            *graph.relations,
            Relation("technical-root", technical.id, RelationPredicate.DERIVED_FROM, root.id),
            Relation("technical-physical", technical.id, RelationPredicate.SATISFIED_BY, physical.id),
        ),
        revision=graph.revision,
    )

    report = MethodologyEngine().analyze(graph)

    assert report.metrics["functional_requirement_coverage"] == 1.0
    assert not any(
        item.code == "functional_requirement_uncovered" and technical.id in item.entity_ids
        for item in report.findings
    )
    assert any(
        item.code == "verification_missing" and technical.id in item.entity_ids
        for item in report.findings
    )


def test_vertical_guidance_contains_bounded_requirement_coverage_gaps():
    graph = _graph(complete_vv=True)
    missing = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"level": "system"},
    )
    graph = ModelGraph(
        graph.project_id,
        (*graph.entities, missing),
        graph.relations,
        revision=graph.revision,
    )

    guidance = MethodologyEngine().context_guidance(graph, "vertical.functional")
    coverage = guidance["stage_completion"]["checks"][-1]

    assert coverage["id"] == "requirement_coverage:functional"
    assert coverage["stage"] == "functional"
    assert coverage["missing_requirement_ids"] == [missing.id]
    assert coverage["gaps"][0]["requirement_id"] == missing.id
    assert len(coverage["gaps"]) <= 24
    assert guidance["requirement_coverage"] == coverage
