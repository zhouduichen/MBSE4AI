from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, apply_patch
from rflp_lite.methodology.contracts import ContextBundle, TaskExecutionRequest
from rflp_lite.methodology.engine import MethodologyEngine
from rflp_lite.runtime.rule_based import _partition_functions, _partition_label
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_partition_functions_uses_explicit_key_and_falls_back_to_function_id():
    first = make_entity(EntityKind.FUNCTION, "规划", {"partition_key": "任务管理"})
    second = make_entity(EntityKind.FUNCTION, "执行", {"partition_key": "任务管理"})
    third = make_entity(EntityKind.FUNCTION, "监控", {})

    groups = _partition_functions((first, second, third))

    assert [[item.meta.name for item in group] for group in groups] == [
        ["规划", "执行"],
        ["监控"],
    ]


def test_partition_functions_groups_shared_state_and_exposes_labels():
    first = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    second = make_entity(EntityKind.FUNCTION, "调度", {"shared_state": ["任务状态"]})

    groups = _partition_functions((first, second))

    assert len(groups) == 1
    assert _partition_label(groups[0]) == "共享状态：任务状态"


def test_shared_state_partition_is_reviewable_for_high_coupling():
    first = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    second = make_entity(EntityKind.FUNCTION, "调度", {"shared_state": ["任务状态"]})
    context = ContextBundle(
        "robot",
        "vertical.logical",
        0,
        (first, second),
    )
    request = TaskExecutionRequest(
        "vertical.logical",
        "v2.1",
        context,
        (),
        {"output_kinds": ["logical_component"]},
        100,
    )

    response = VerticalRuleRuntime().execute(request)
    graph = apply_patch(ModelGraph("robot", (first, second)), response.patch)
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)
    report = MethodologyEngine().analyze(graph)

    assert logical.payload["coupling"] == "high"
    assert any(item.code == "logical_partition_needs_review" for item in report.findings)
