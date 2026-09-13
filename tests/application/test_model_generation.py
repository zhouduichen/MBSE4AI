from pathlib import Path

import pytest

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relation, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.application.model_generation import build_traceability_summary
from rflp_lite.application.model_generation import ModelGenerationService
from rflp_lite.application.tool_layer import ToolResult
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
from rflp_lite.methodology.controller import ControllerAction, ControllerPlan
from rflp_lite.ports.generative_model import GenerationResponse
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


class ScriptedModel:
    def __init__(self):
        self.calls = []
        self.relation_contexts = []
        self.controller_decisions = []
        self.evidence_contexts = []

    def complete_json(self, request):
        self.calls.append(request.lens_id)
        self.relation_contexts.append(request.user_payload["context"]["relations"])
        self.controller_decisions.append(request.user_payload["controller_decisions"])
        self.evidence_contexts.append(request.user_payload["evidence"])
        entities = request.user_payload["context"]["entities"]
        by_kind = {}
        for item in entities:
            by_kind.setdefault(item["kind"], []).append(item)
        payload = {"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": request.lens_id}

        def entity(local_ref, kind, name, data):
            payload["entities"].append({"local_ref": local_ref, "kind": kind, "name": name, "payload": data, "confidence": 0.9, "source_ids": [], "evidence_ids": [], "lifecycle_ids": []})

        def relation(source_ref, predicate, target_ref):
            payload["relations"].append({"source_ref": source_ref, "predicate": predicate, "target_ref": target_ref, "evidence_ids": []})

        requirements = by_kind.get("requirement", [])
        if request.lens_id == "vertical.requirements":
            entity("system", "system", "校园配送系统", {"mission": "完成校园配送", "system_boundary": {"inside": ["配送服务"], "outside": ["校园环境"]}, "objectives": ["按时完成任务"], "environment_assumptions": ["道路可通行"], "exclusions": [], "open_questions": []})
            entity("stakeholder", "stakeholder", "配送运营人员", {"role": "任务运营"})
            entity("concern", "concern", "任务可靠性与运营可用性", {"topic": "异常场景下任务仍可追踪"})
            entity("lifecycle", "lifecycle_stage", "设计—运行生命周期", {"stage": "operation", "sequence": ["设计", "部署", "运行", "维护"]})
            entity("hypothesis", "scenario_hypothesis", "典型配送场景假设", {"category": "normal", "trigger": "提交配送任务", "outcome": "完成任务"})
            entity("use_case", "use_case", "执行一次配送任务", {"primary_actor": "配送运营人员", "goal": "完成可追踪配送"})
            entity("scenario", "operational_scenario", "典型配送场景", {"actor_ids": ["stakeholder"], "steps": ["提交任务", "完成配送"], "exchanges": [], "internal_component_ids": []})
            entity("activity", "activity", "受理并完成配送活动", {"steps": ["受理", "执行", "反馈"], "branches": ["人工接管"]})
            relation("stakeholder", "hasConcern", "concern")
            relation("system", "decomposes", "stakeholder")
            relation("stakeholder", "participatesIn", "scenario")
            relation("stakeholder", "derivedFrom", "hypothesis")
            relation("use_case", "derivedFrom", "hypothesis")
            relation("scenario", "derivedFrom", "use_case")
            relation("activity", "occursIn", "lifecycle")
            if requirements:
                relation(requirements[0]["id"], "derivedFrom", "activity")
        elif request.lens_id == "vertical.functional":
            entity("function", "function", "规划并执行配送", {"behavior": "根据任务完成配送", "inputs": ["任务"], "outputs": ["结果"]})
            entity("flow", "functional_flow", "任务结果流", {"content": "任务和结果"})
            entity("fscenario", "functional_scenario", "完成配送功能场景", {"function_ids": ["function"], "steps": ["输入", "处理", "输出"]})
            if requirements:
                relation(requirements[0]["id"], "satisfiedBy", "function")
            relation("function", "exchangesWith", "flow")
        elif request.lens_id == "vertical.logical":
            functions = by_kind.get("function", [])
            entity("logical", "logical_component", "配送控制组件", {"responsibility": "协调配送功能", "interfaces": []})
            entity("interface", "interface", "配送服务接口", {"protocol": "logical-message", "exchanges": ["request", "response"]})
            entity("state", "state", "配送任务状态", {"values": ["待受理", "执行中", "人工接管", "完成", "失败"], "transitions": ["待受理->执行中", "执行中->完成"]})
            if functions:
                relation(functions[0]["id"], "allocatedTo", "logical")
                relation(functions[0]["id"], "exchangesWith", "interface")
            relation("logical", "decomposes", "state")
        elif request.lens_id == "vertical.physical":
            entity("physical", "physical_block", "配送执行单元", {"candidate_type": "可部署执行单元", "constraints": ["满足逻辑职责"], "rationale": "承载配送控制"})
            logical = by_kind.get("logical_component", [])
            if logical:
                relation(logical[0]["id"], "allocatedTo", "physical")
        elif request.lens_id == "vertical.verification_validation":
            entity("verification", "verification_case", "验证配送需求", {"method": "test", "precondition": "系统处于可测试初始状态", "input": "配送任务", "procedure": "执行测试步骤并记录实际结果", "expected_result": "实际结果满足需求目标", "pass_criteria": "测试结果满足需求", "requirement_ids": [requirements[0]["id"]] if requirements else [], "scenario_ids": [], "activity_ids": [], "covered_branches": ["人工接管"], "evidence_ids": []})
            entity("validation", "validation_case", "确认配送体验", {"method": "demonstration", "precondition": "目标用户和典型场景可用", "input": "配送任务", "procedure": "在典型场景执行并收集用户反馈", "expected_result": "用户场景目标达成", "pass_criteria": "用户场景确认通过", "requirement_ids": [requirements[0]["id"]] if requirements else [], "scenario_ids": [], "activity_ids": [], "covered_branches": ["人工接管"], "evidence_ids": []})
            entity("hazard", "hazard", "风险：配送任务失败", {"description": "异常分支导致任务目标未达成", "requirement_ids": [requirements[0]["id"]] if requirements else [], "branches": ["人工接管"]})
            entity("failure", "failure_mode", "失效模式：任务未完成", {"effect": "需求未满足", "cause": "执行条件异常", "requirement_ids": [requirements[0]["id"]] if requirements else []})
            if requirements:
                relation(requirements[0]["id"], "verifiedBy", "verification")
                relation(requirements[0]["id"], "validatedBy", "validation")
                relation("hazard", "derivedFrom", requirements[0]["id"])
            relation("hazard", "causes", "failure")
            relation("hazard", "mitigatedBy", "verification")
            relation("failure", "mitigatedBy", "verification")
        payload["assumptions"] = ["脚本模型用于测试结构化边界"]
        payload["open_questions"] = []
        payload["decision_records"] = [{
            "step": request.lens_id,
            "decision": "按照阶段契约产生结构化模型",
            "basis": [],
        }]
        return GenerationResponse(request.lens_id, payload, "input", "output", False, "fake", "scripted")


class SemanticInvalidModel(ScriptedModel):
    def complete_json(self, request):
        response = super().complete_json(request)
        if request.lens_id == "vertical.functional":
            response.payload["entities"][0]["name"] = "配送传感器控制"
        return response


class IncompleteOperationalModel(ScriptedModel):
    def complete_json(self, request):
        response = super().complete_json(request)
        if request.lens_id == "vertical.requirements":
            keep = {"system", "stakeholder", "scenario"}
            response.payload["entities"] = [
                item for item in response.payload["entities"] if item["local_ref"] in keep
            ]
            response.payload["relations"] = [
                item for item in response.payload["relations"]
                if item["source_ref"] in keep and item["target_ref"] in keep
            ]
        return response


class LockedTriggerUpdateRuntime(VerticalRuleRuntime):
    def __init__(self):
        self.mutate_locked_trigger = False

    def execute(self, request):
        if self.mutate_locked_trigger and request.task_id == "vertical.logical":
            function = next(
                item for item in request.context_bundle.entities
                if item.kind is EntityKind.FUNCTION
            )
            patch = Patch.create(
                request.context_bundle.project_id,
                request.task_id,
                (UpdateEntity(function.id, {"payload": {"tampered": True}}),),
                "测试尝试修改锁定实体",
                request.context_bundle.revision,
            )
            return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch)
        return super().execute(request)


class _ControllerEvidenceTool:
    def __init__(self):
        self.calls = []

    def collect_evidence(self, project_id, graph, action):
        self.calls.append((project_id, graph.revision, action["id"]))
        return ToolResult(
            "evidence.test",
            "completed",
            "physical power evidence",
            ({
                "id": "evidence-controller-test",
                "source_type": "test",
                "source_id": "test-source",
                "locator": "test",
                "claim": "功耗测量",
                "excerpt": "功耗为 40 W",
                "relevance": 1.0,
            },),
        )


def _trace_graph(*, verification: bool, validation: bool) -> ModelGraph:
    requirement = make_entity(EntityKind.REQUIREMENT, "系统应完成配送", {"obligation": "系统应"})
    function = make_entity(EntityKind.FUNCTION, "规划配送", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "规划组件", status=EntityStatus.VALIDATED)
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "计算单元", status=EntityStatus.VALIDATED)
    entities = [requirement, function, logical, physical]
    relations = [
        Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
    ]
    if verification:
        case = make_entity(
            EntityKind.VERIFICATION_CASE,
            "验证配送",
            {"method": "test", "pass_criteria": "满足需求"},
            status=EntityStatus.VALIDATED,
        )
        entities.append(case)
        relations.append(Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, case.id))
    if validation:
        case = make_entity(
            EntityKind.VALIDATION_CASE,
            "确认体验",
            {"method": "demonstration", "pass_criteria": "用户认可"},
            status=EntityStatus.VALIDATED,
        )
        entities.append(case)
        relations.append(Relation("r-va", requirement.id, RelationPredicate.VALIDATED_BY, case.id))
    return ModelGraph("trace", tuple(entities), tuple(relations), revision=1)


def test_generation_creates_real_rflp_and_vv_objects_from_one_requirement(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园配送机器人")

    result = services.generation("robot").generate(
        "robot",
        requirement_text="系统应在校园内自主完成配送并支持人工接管",
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert {
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.HAZARD,
        EntityKind.FAILURE_MODE,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    } <= {item.kind for item in graph.entities}
    assert result.traceability.complete_count >= 1
    assert result.methodology.metrics["logical_allocation_coverage"] == 1.0
    assert result.methodology.metrics["physical_feasibility"] == "needs_measurement"
    assert any(
        finding.code == "physical_measurement_required"
        for finding in result.methodology.findings
    )
    assert any(
        event["kind"] == "model_generation.methodology_analyzed"
        for event in services.repository("robot").list_audit_events("robot")
    )
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    assert logical.payload["partition_basis"]
    assert logical.payload["cohesion"] == "high"
    assert physical.payload["feasibility"]["status"] == "needs_measurement"
    assert physical.payload["swap_c"]["status"] == "requires_measurement"
    assert {record["step"] for record in result.stage_results[2].decision_records} >= {
        "dependency_clustering", "architecture_evaluation"
    }
    assert all(
        "候选" not in item.meta.name and "待确认" not in item.meta.name
        for item in graph.entities
        if item.meta.producer is Producer.RULE
    )


def test_generation_is_recorded_as_one_five_stage_run(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    run = services.repository("robot").load_run("robot", result.run_id)

    assert run is not None
    assert run.phase == "vertical_generation"
    assert {step.task_id for step in run.steps} == {
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    }
    assert all(step.status == "completed" for step in run.steps)


def test_generation_uses_structured_llm_runtime_for_all_five_stages(tmp_path: Path):
    model = ScriptedModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.status == "completed"
    assert model.calls == [
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ]
    assert result.traceability.complete_count == 1
    assert result.stage_results[2].decision_records[0]["step"] == "vertical.logical"
    relation_context = [
        model_relation
        for context in model.relation_contexts
        for model_relation in context
    ]
    assert any(model_relation["predicate"] == "satisfiedBy" for model_relation in relation_context)
    assert {"id", "source_id", "predicate", "target_id", "evidence_ids"} <= set(relation_context[0])


def test_controller_decision_is_passed_to_downstream_structured_runtime(tmp_path: Path):
    model = ScriptedModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    requirement_id = next(
        item.id for item in services.model("robot").graph("robot").entities
        if item.kind is EntityKind.REQUIREMENT
    )
    decision = {
        "action_id": "controller-action-test",
        "option_id": "trade-option-test",
        "option": "更换物理候选或计算架构",
        "task_id": "allocation_tradeoff",
    }

    result = services.generation("robot").reanalyze(
        "robot",
        requirement_id,
        expected_revision=generated.revision,
        controller_decision=decision,
    )

    assert result["controller_decision"] == decision
    assert any(decision in context for context in model.controller_decisions)


def test_document_regions_are_available_as_structured_generation_evidence(tmp_path: Path):
    model = ScriptedModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")
    services.projects.ingest_uploaded(
        "robot", "requirements.txt", "系统应支持人工接管\n".encode()
    )

    result = services.generation("robot").generate("robot")

    assert result.status == "completed"
    assert any(
        evidence["source_type"] == "document_region"
        and evidence["excerpt"] == "系统应支持人工接管"
        for context in model.evidence_contexts
        for evidence in context
    )


def test_controller_evidence_action_calls_tool_and_reanalyzes(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    repository = services.repository("robot")
    tool = _ControllerEvidenceTool()
    generation = ModelGenerationService(repository, VerticalRuleRuntime(), tool_layer=tool)
    generated = generation.generate("robot", requirement_text="系统应支持人工接管")
    action = generated.controller.next_action

    assert action is not None
    assert action.kind == "collect_evidence"
    result = generation.execute_controller_action(
        "robot",
        action_id=action.id,
        expected_revision=generated.revision,
    )

    assert result["execution_status"] == "completed"
    assert tool.calls == [("robot", generated.revision, action.id)]
    assert repository.list_evidence("robot")[0]["id"] == "evidence-controller-test"
    assert result["reanalysis"]["controller_decision"]["kind"] == "evidence_collected"


def test_controller_iteration_finishes_without_actions(tmp_path: Path, monkeypatch):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")
    monkeypatch.setattr(
        generation.controller,
        "plan",
        lambda graph, report=None, max_actions=8: ControllerPlan("complete", "模型已完成"),
    )

    result = generation.iterate_controller("robot")

    assert result["execution_status"] == "completed"
    assert result["iterations"] == []
    assert result["start_revision"] == result["revision"] == 0


def test_controller_iteration_waits_for_input_on_empty_project(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").iterate_controller("robot")

    assert result["execution_status"] == "awaiting_input"
    assert result["iterations"] == []
    assert result["controller"]["next_action"]["kind"] == "collect_input"


def test_controller_iteration_stops_when_evidence_tool_waits(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    result = services.generation("robot").iterate_controller(
        "robot", expected_revision=generated.revision
    )

    assert result["execution_status"] == "awaiting_evidence"
    assert len(result["iterations"]) == 1
    assert result["iterations"][0]["action"]["kind"] == "collect_evidence"
    assert result["revision"] == generated.revision


def test_controller_iteration_rejects_invalid_budget(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    with pytest.raises(ContractViolation, match="between 1 and 8"):
        services.generation("robot").iterate_controller("robot", max_iterations=0)


def test_controller_iteration_stops_at_trade_study_without_mutating_graph(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    services.review("robot").edit_entity(
        "robot", requirement.id,
        payload={"constraints": {"max_power_w": 50}},
        expected_revision=graph.revision,
    )
    graph = services.model("robot").graph("robot")
    services.review("robot").edit_entity(
        "robot", physical.id,
        payload={"power_w": 80},
        expected_revision=graph.revision,
    )
    before = services.model("robot").graph("robot").revision

    result = services.generation("robot").iterate_controller("robot", max_iterations=3)

    assert result["execution_status"] == "awaiting_decision"
    assert result["revision"] == before
    assert result["iterations"] == []
    assert result["controller"]["next_action"]["kind"] == "trade_study"
    assert generated.revision < before


def test_controller_iteration_reports_no_progress_for_repeated_action(tmp_path: Path, monkeypatch):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")
    action = ControllerAction(
        "controller-action-test", "reanalyze", "functional_interaction", "functional", "P1",
        ("function-1",), "补足功能流"
    )
    plan = ControllerPlan("needs_action", "推进模型", ("functional_flow_missing",), (action,))
    monkeypatch.setattr(
        generation.controller,
        "plan",
        lambda graph, report=None, max_actions=8: plan,
    )
    monkeypatch.setattr(
        generation,
        "execute_controller_action",
        lambda project_id, **kwargs: {
            "execution_status": "completed",
            "action": action.as_dict(),
            "reanalysis": {"execution_status": "completed", "revision": 0},
        },
    )

    result = generation.iterate_controller("robot", max_iterations=3)

    assert result["execution_status"] == "no_progress"
    assert len(result["iterations"]) == 1
    assert result["iterations"][0]["revision_before"] == result["iterations"][0]["revision_after"] == 0
    events = services.repository("robot").list_audit_events("robot")
    assert any(item["kind"] == "controller.iteration.started" for item in events)
    assert any(item["kind"] == "controller.iteration.no_progress" for item in events)


def test_controller_iteration_stops_at_iteration_budget(tmp_path: Path, monkeypatch):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")
    repository = services.repository("robot")
    action = ControllerAction(
        "controller-action-progress", "reanalyze", "functional_interaction", "functional", "P1",
        (), "持续补足功能流"
    )
    plan = ControllerPlan("needs_action", "推进模型", ("functional_flow_missing",), (action,))
    monkeypatch.setattr(
        generation.controller,
        "plan",
        lambda graph, report=None, max_actions=8: plan,
    )

    def progress(project_id, **kwargs):
        graph = repository.load_graph(project_id)
        entity = make_entity(EntityKind.CONCERN, f"progress-{graph.revision}")
        patch = Patch.create(
            project_id,
            "controller.progress.test",
            (AddEntity(entity),),
            "测试 Controller 迭代进展",
            graph.revision,
        )
        repository.append_patch(project_id, patch, graph.revision)
        return {
            "execution_status": "completed",
            "action": action.as_dict(),
            "reanalysis": {"execution_status": "completed"},
        }

    monkeypatch.setattr(generation, "execute_controller_action", progress)

    result = generation.iterate_controller("robot", max_iterations=2)

    assert result["execution_status"] == "max_iterations"
    assert len(result["iterations"]) == 2
    assert result["revision"] == 2


def test_semantic_invalid_output_stays_candidate_and_creates_review_issue(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(SemanticInvalidModel()),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)

    assert result.status == "completed_with_warnings"
    assert result.stage_results[1].status == "needs_review"
    assert function.meta.status is EntityStatus.CANDIDATE
    assert any(item["code"] == "semantic_invalid" for item in services.model("robot").issues("robot"))


def test_incomplete_operational_stage_is_marked_for_review(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(IncompleteOperationalModel()),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.status == "completed_with_warnings"
    assert result.stage_results[0].status == "needs_review"
    assert any("missing required kinds" in warning for warning in result.warnings)


def test_traceability_requires_both_verification_and_validation():
    rflp = build_traceability_summary(_trace_graph(verification=False, validation=False))
    verified = build_traceability_summary(_trace_graph(verification=True, validation=False))
    validated = build_traceability_summary(_trace_graph(verification=False, validation=True))
    complete = build_traceability_summary(_trace_graph(verification=True, validation=True))

    assert rflp.rflp_complete_count == 1
    assert verified.verification_complete_count == 1
    assert validated.validation_complete_count == 1
    assert verified.end_to_end_complete_count == 0
    assert validated.end_to_end_complete_count == 0
    assert complete.end_to_end_complete_count == 1
    assert complete.complete_count == complete.end_to_end_complete_count


def test_reanalysis_runs_only_from_changed_entity_stage_downstream(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)

    result = services.generation("robot").reanalyze("robot", function.id)

    assert result["execution_status"] == "completed"
    assert result["selected_stages"] == [
        "functional", "logical", "physical", "verification_validation"
    ]
    assert function.id in result["methodology"]["impacted_entity_ids"]
    assert result["methodology"]["recommended_tasks"]
    assert len(result["stage_results"]) == 4


def test_continue_generation_runs_only_downstream_and_preserves_trigger(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    accepted = services.review("robot").accept_entity(
        "robot", function.id, expected_revision=graph.revision
    )
    before = services.model("robot").graph("robot").entity_index[function.id]

    result = services.generation("robot").continue_generation(
        "robot", function.id, expected_revision=accepted.revision["sequence"]
    )

    assert result["execution_status"] == "completed"
    assert result["selected_stages"] == [
        "logical", "physical", "verification_validation"
    ]
    assert result["run_id"] != generated.run_id
    after = services.model("robot").graph("robot").entity_index[function.id]
    assert after.id == before.id
    assert after.meta.status is before.meta.status
    assert after.meta.name == before.meta.name
    assert after.payload == before.payload
    assert after.meta.updated_revision == before.meta.updated_revision


def test_candidate_cannot_continue_until_user_accepts_it(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    edited = services.review("robot").edit_entity(
        "robot",
        function.id,
        name="人工修改后的功能",
        expected_revision=graph.revision,
    )

    with pytest.raises(ContractViolation, match="accepted or locked"):
        services.generation("robot").continue_generation(
            "robot", function.id, expected_revision=edited.revision["sequence"]
        )


def test_locked_trigger_is_read_only_during_continuation(tmp_path: Path):
    runtime = LockedTriggerUpdateRuntime()
    services = build_v2_services(tmp_path / "workspaces", runtime=runtime)
    services.projects.create("robot")
    services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    accepted = services.review("robot").accept_entity(
        "robot", function.id, expected_revision=graph.revision
    )
    locked = services.review("robot").lock_entity(
        "robot", function.id, expected_revision=accepted.revision["sequence"]
    )
    before_graph = services.model("robot").graph("robot")
    before = before_graph.entity_index[function.id]
    runtime.mutate_locked_trigger = True

    result = services.generation("robot").continue_generation(
        "robot", function.id, expected_revision=locked.revision["sequence"]
    )

    assert result["execution_status"] == "failed"
    after_graph = services.model("robot").graph("robot")
    after = after_graph.entity_index[function.id]
    assert after_graph.revision == before_graph.revision
    assert after.id == before.id
    assert after.meta.status is before.meta.status
    assert after.payload == before.payload
    run = services.repository("robot").load_run("robot", result["run_id"])
    assert run is not None
    assert run.status == "failed"


def test_vv_continuation_has_no_downstream_work_and_no_revision(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    validation = next(
        item for item in graph.entities if item.kind is EntityKind.VALIDATION_CASE
    )
    accepted = services.review("robot").accept_entity(
        "robot", validation.id, expected_revision=graph.revision
    )

    result = services.generation("robot").continue_generation(
        "robot", validation.id, expected_revision=accepted.revision["sequence"]
    )

    assert result["execution_status"] == "no_downstream_work"
    assert result["run_id"] is None
    assert result["revision"] == accepted.revision["sequence"]
    assert services.model("robot").graph("robot").revision == result["revision"]
