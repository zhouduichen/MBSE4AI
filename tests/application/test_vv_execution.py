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
    finding = next(
        item for item in result.methodology["findings"]
        if item["code"] == "verification_execution_failed"
        and verification.id in item["entity_ids"]
    )
    assert finding["impact_paths"]
    assert any(item.startswith("function-") for item in finding["entity_ids"])
    assert any(item.startswith("logical_component-") for item in finding["entity_ids"])
    assert any(item.startswith("physical_block-") for item in finding["entity_ids"])
    issue = next(
        item for item in services.model("robot").issues("robot")
        if item["code"] == "verification_execution_failed"
    )
    assert any(item.startswith("function-") for item in issue["entity_ids"])
    assert result.controller["next_action"]["task_id"] == "function_identification"
    assert any(
        item.startswith("function-")
        for item in result.controller["next_action"]["entity_ids"]
    )


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


def test_vv_failure_can_drive_targeted_downstream_iteration(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
    )
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    verification = next(
        item for item in services.model("robot").graph("robot").entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )
    failed = services.vv("robot").record_result(
        "robot",
        verification.id,
        outcome="failed",
        claim="响应时间不满足要求",
        excerpt="测试结果超过通过准则",
        expected_revision=generated.revision,
    )

    iteration = services.generation("robot").iterate_controller(
        "robot",
        max_iterations=1,
        expected_revision=failed.revision,
    )

    assert iteration["execution_status"] == "awaiting_decision"
    assert iteration["iterations"] == []
    action = iteration["controller"]["next_action"]
    assert action["kind"] == "trade_study"
    assert {item["task_id"] for item in action["options"]} >= {
        "function_identification", "allocation_tradeoff",
        "system_requirement_derivation",
    }


def test_vv_failure_trade_study_can_select_a_new_physical_candidate(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
    )
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    verification = next(
        item for item in services.model("robot").graph("robot").entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )
    failed = services.vv("robot").record_result(
        "robot",
        verification.id,
        outcome="failed",
        claim="响应时间不满足要求",
        excerpt="测试结果超过通过准则",
        expected_revision=generated.revision,
    )
    action = failed.controller["next_action"]
    physical_option = next(
        item for item in action["options"]
        if item["task_id"] == "allocation_tradeoff"
    )

    selected = services.generation("robot").execute_controller_action(
        "robot",
        action_id=action["id"],
        option_id=physical_option["id"],
        expected_revision=failed.revision,
    )

    assert selected["execution_status"] == "completed"
    assert selected["decision"]["task_id"] == "allocation_tradeoff"
    assert selected["reanalysis"]["selected_stages"] == [
        "physical", "verification_validation"
    ]
    assert selected["reanalysis"]["revision"] > failed.revision
    assert any(
        item.kind is EntityKind.PHYSICAL_BLOCK
        and item.payload.get("candidate_variant") == "alternative"
        for item in services.model("robot").graph("robot").entities
    )
