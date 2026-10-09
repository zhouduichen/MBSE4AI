from __future__ import annotations

from pathlib import Path

from rflp_lite.application.pipeline_report import PipelineReportService
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def _services_with_complete_trace(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
        status=EntityStatus.VALIDATED,
    )
    function = make_entity(
        EntityKind.FUNCTION,
        "执行人工接管",
        status=EntityStatus.VALIDATED,
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "任务控制器",
        status=EntityStatus.VALIDATED,
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "控制计算单元",
        status=EntityStatus.VALIDATED,
    )
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "人工接管测试",
        {
            "method": "test",
            "verification_objective": "证明人工接管可用",
            "precondition": "设备已部署",
            "test_condition": "典型运行环境",
            "input": "接管请求",
            "stimulus": "发起人工接管",
            "procedure": "执行接管并记录结果",
            "expected_result": "系统进入人工接管状态",
            "pass_criteria": "接管成功",
        },
        status=EntityStatus.VALIDATED,
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "人工接管确认",
        {
            "method": "demonstration",
            "verification_objective": "确认用户可以完成接管",
            "precondition": "操作员和设备可用",
            "test_condition": "典型任务场景",
            "input": "接管任务",
            "stimulus": "操作员发起接管",
            "procedure": "观察操作员完成接管",
            "expected_result": "操作员确认目标达成",
            "pass_criteria": "操作员确认",
        },
        status=EntityStatus.VALIDATED,
    )
    scope = {
        "requirement_ids": [requirement.id],
        "function_ids": [function.id],
        "logical_component_ids": [logical.id],
        "physical_ids": [physical.id],
    }
    verification = verification.__class__(
        verification.meta,
        {**verification.payload, **scope},
    )
    validation = validation.__class__(validation.meta, {**validation.payload, **scope})
    graph = services.model("robot").graph("robot")
    services.repository("robot").append_patch(
        "robot",
        Patch.create(
            "robot",
            "fixture.complete-trace",
            (
                AddEntity(requirement),
                AddEntity(function),
                AddEntity(logical),
                AddEntity(physical),
                AddEntity(verification),
                AddEntity(validation),
                Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
                Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id),
                Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
                Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
                Relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
            ),
            "complete trace fixture",
            graph.revision,
        ),
        graph.revision,
    )
    return services


def test_pipeline_report_is_read_only_and_contains_engineering_result(tmp_path: Path):
    services = _services_with_complete_trace(tmp_path)
    repository = services.repository("robot")
    before = repository.load_graph("robot")
    before_runs = repository.list_runs("robot")
    before_patches = repository.list_patches("robot")

    report = PipelineReportService(repository).build("robot")

    after = repository.load_graph("robot")
    assert report["traceability"]["complete_count"] == 1
    assert report["methodology"]["metrics"]
    assert "findings" in report["methodology"]
    assert "actions" in report["controller"]
    assert report["report_revision"] == before.revision == after.revision
    assert report["report_snapshot_hash"] == before.snapshot_hash == after.snapshot_hash
    assert repository.list_runs("robot") == before_runs
    assert repository.list_patches("robot") == before_patches
