from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.vertical_coverage import (
    build_requirement_worklist,
    resolve_requirement_trace,
    resolve_rflp_paths,
    resolve_vertical_coverage,
)


def _make(kind, name, payload=None, *, status=EntityStatus.VALIDATED):
    return make_entity(
        kind,
        name,
        payload,
        status=status,
        producer=Producer.RULE,
    )


def _two_requirement_graph() -> tuple[ModelGraph, object, object]:
    first = _make(EntityKind.REQUIREMENT, "系统应完成配送", {"level": "system"})
    second = _make(EntityKind.REQUIREMENT, "系统应支持人工接管", {"level": "system"})
    function = _make(EntityKind.FUNCTION, "执行配送")
    logical = _make(EntityKind.LOGICAL_COMPONENT, "配送控制逻辑")
    physical = _make(EntityKind.PHYSICAL_BLOCK, "配送执行平台")
    verification = _make(
        EntityKind.VERIFICATION_CASE,
        "验证配送",
        {
            "requirement_ids": [first.id],
            "function_ids": [function.id],
            "logical_component_ids": [logical.id],
            "physical_ids": [physical.id],
        },
    )
    validation = _make(
        EntityKind.VALIDATION_CASE,
        "确认配送",
        {
            "requirement_ids": [first.id],
            "function_ids": [function.id],
            "logical_component_ids": [logical.id],
            "physical_ids": [physical.id],
        },
    )
    deprecated_function = _make(
        EntityKind.FUNCTION,
        "已废弃人工接管功能",
        status=EntityStatus.DEPRECATED,
    )
    relations = (
        Relation("r-f", first.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relation("r-v", first.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relation("r-va", first.id, RelationPredicate.VALIDATED_BY, validation.id),
        Relation("deprecated-r-f", second.id, RelationPredicate.SATISFIED_BY, deprecated_function.id),
    )
    graph = ModelGraph(
        "coverage",
        (first, second, function, logical, physical, verification, validation, deprecated_function),
        relations,
        revision=4,
    )
    return graph, first, second


def _row(result, requirement_id):
    return next(item for item in result.rows if item.requirement_id == requirement_id)


def test_functional_coverage_names_the_requirement_missing_a_live_function():
    graph, first, second = _two_requirement_graph()

    result = resolve_vertical_coverage(graph, "functional")

    assert result.passed is False
    assert _row(result, first.id).missing == ()
    assert _row(result, second.id).missing == ("function",)
    assert _row(result, second.id).function_ids == ()


def test_logical_and_physical_coverage_preserve_the_earliest_gap():
    graph, first, second = _two_requirement_graph()

    logical = resolve_vertical_coverage(graph, "logical")
    physical = resolve_vertical_coverage(graph, "physical")

    assert _row(logical, first.id).path == (
        first.id,
        _row(logical, first.id).function_ids[0],
        _row(logical, first.id).logical_component_ids[0],
    )
    assert _row(logical, second.id).missing == ("function", "logical_component")
    assert _row(physical, second.id).missing == (
        "function",
        "logical_component",
        "physical",
    )


def test_assurance_coverage_requires_both_typed_cases_and_matching_scope():
    graph, first, second = _two_requirement_graph()

    result = resolve_vertical_coverage(graph, "verification_validation")

    assert result.passed is False
    assert _row(result, first.id).missing == ()
    assert _row(result, second.id).missing == ("verification", "validation")


def test_technical_requirement_can_use_direct_physical_satisfaction():
    requirement = _make(
        EntityKind.REQUIREMENT,
        "系统功耗不超过 50 W",
        {"level": "technical", "constraints": {"max_power_w": 50}},
    )
    physical = _make(EntityKind.PHYSICAL_BLOCK, "功耗受限计算平台")
    graph = ModelGraph(
        "technical",
        (requirement, physical),
        (Relation("technical-p", requirement.id, RelationPredicate.SATISFIED_BY, physical.id),),
        revision=1,
    )

    result = resolve_vertical_coverage(graph, "physical")

    assert result.passed is True
    assert _row(result, requirement.id).physical_ids == (physical.id,)


def test_canonical_trace_returns_ready_targets_and_semantic_coverage():
    graph, first, _second = _two_requirement_graph()

    trace = resolve_requirement_trace(graph, first.id)

    assert trace.function_ids
    assert trace.logical_component_ids
    assert trace.physical_ids
    assert trace.verification_case_ids
    assert trace.validation_case_ids
    assert trace.gaps == ()
    assert trace.stage_coverage == {
        "functional": True,
        "logical": True,
        "physical": True,
        "verification": True,
        "validation": True,
    }
    assert trace.primary_path == (
        first.id,
        trace.function_ids[0],
        trace.logical_component_ids[0],
        trace.physical_ids[0],
    )
    assert trace.complete is True


def test_canonical_trace_excludes_non_ready_targets_and_reports_scope_gaps():
    graph, first, _second = _two_requirement_graph()
    verification = next(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )
    stale = verification.__class__(
        verification.meta,
        {**verification.payload, "physical_ids": []},
    )
    graph = ModelGraph(
        graph.project_id,
        tuple(stale if item.id == stale.id else item for item in graph.entities),
        graph.relations,
        graph.revision,
    )

    trace = resolve_requirement_trace(graph, first.id)

    assert trace.function_ids
    assert "verification_scope" in trace.gaps
    assert "validation" not in trace.gaps
    assert trace.stage_coverage["verification"] is False
    assert trace.complete is False


def test_canonical_rflp_paths_are_deterministic_and_ready_only():
    graph, first, second = _two_requirement_graph()
    physical = resolve_vertical_coverage(graph, "physical")
    row = _row(physical, first.id)

    assert resolve_rflp_paths(graph, first.id) == (
        (first.id, row.function_ids[0], row.logical_component_ids[0], row.physical_ids[0]),
    )
    assert resolve_rflp_paths(graph, second.id) == ()


def test_requirement_worklist_exposes_current_path_and_exact_gap():
    graph, first, second = _two_requirement_graph()

    worklist = build_requirement_worklist(graph, "logical")

    assert worklist["stage"] == "logical"
    assert worklist["total_count"] == 2
    assert worklist["truncated"] is False
    first_item = next(item for item in worklist["items"] if item["requirement_id"] == first.id)
    second_item = next(item for item in worklist["items"] if item["requirement_id"] == second.id)
    assert first_item["current"]["logical_component_ids"]
    assert first_item["path"][-1] == first_item["current"]["logical_component_ids"][0]
    assert second_item["missing"] == ["function", "logical_component"]
