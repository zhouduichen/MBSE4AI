from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_vv_execution_result_is_persisted_and_failure_routes_iteration(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
    )
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    verification = next(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )

    result = services.vv("robot").record_result(
        "robot",
        verification.id,
        outcome="failed",
        claim="人工接管响应超时",
        excerpt="测试日志显示响应时间为 4.2 s，超过通过准则。",
        locator="test-results/handover.log:42",
        expected_revision=generated.revision,
    )

    updated = services.model("robot").graph("robot")
    case = updated.entity_index[verification.id]
    assert result.outcome == "failed"
    assert result.revision == updated.revision
    assert case.payload["execution_status"] == "failed"
    assert result.evidence_id in case.payload["evidence_ids"]
    assert any(
        item["code"] == "verification_execution_failed"
        and verification.id in item["entity_ids"]
        for item in result.methodology["findings"]
    )
    assert any(
        item["code"] == "verification_execution_failed"
        for item in services.model("robot").issues("robot")
    )
    assert result.controller["next_action"]["task_id"] == "function_identification"


def test_vv_execution_pass_resolves_prior_failure_without_duplicate_evidence(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
    )
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    verification = next(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )
    service = services.vv("robot")
    failed = service.record_result(
        "robot", verification.id, outcome="failed", claim="初次失败",
        excerpt="未达到通过准则", expected_revision=generated.revision,
    )
    passed = service.record_result(
        "robot", verification.id, outcome="passed", claim="修复后通过",
        excerpt="重新测试达到通过准则", expected_revision=failed.revision,
    )

    case = services.model("robot").graph("robot").entity_index[verification.id]
    assert case.payload["execution_status"] == "passed"
    assert len(case.payload["execution_records"]) == 2
    assert passed.methodology["metrics"]["vv_execution_failure_count"] == 0
    assert any(
        item["code"] == "verification_execution_failed"
        and item["status"] == "resolved"
        for item in services.model("robot").issues("robot")
    )
