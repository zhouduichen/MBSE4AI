from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.engine import MethodologyEngine


def _graph(*, power_w: float | None = 40, max_power_w: float | None = None, complete_vv: bool = False) -> ModelGraph:
    requirement_payload = {"statement": "系统应在任务期间保持可用"}
    if max_power_w is not None:
        requirement_payload["constraints"] = {"max_power_w": max_power_w}
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
            "swap_c": {"mass_kg": 1.0, "power_w": power_w, "cost": 1000},
            "feasibility": {"status": "candidate"},
        },
        status=EntityStatus.VALIDATED,
    )
    verification_payload = {
        "method": "test",
        "precondition": "设备上电",
        "input": "配送任务",
        "procedure": "执行任务并采集结果",
        "expected_result": "任务完成",
        "pass_criteria": "结果满足需求",
        "evidence_ids": ["evidence-1"],
    }
    validation_payload = {
        "method": "demonstration",
        "precondition": "用户在场",
        "input": "配送任务",
        "procedure": "用户观察执行",
        "expected_result": "用户认可结果",
        "pass_criteria": "场景目标达成",
        "evidence_ids": ["evidence-2"],
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


def test_physical_analysis_distinguishes_conflict_from_unknown_measurement():
    conflict = MethodologyEngine().analyze(_graph(power_w=80, max_power_w=50))
    unknown = MethodologyEngine().analyze(_graph(power_w=None, max_power_w=50))

    assert any(item.code == "physical_constraint_conflict" for item in conflict.findings)
    assert conflict.metrics["physical_feasibility"] == "infeasible"
    assert any(item.code == "physical_measurement_required" for item in unknown.findings)
    assert unknown.metrics["physical_feasibility"] == "needs_measurement"


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
