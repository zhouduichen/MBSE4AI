from pathlib import Path
from dataclasses import replace

import pytest

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation, TransportFailure
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relation, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.application.model_generation import build_traceability_summary
from rflp_lite.application.model_generation import (
    ModelGenerationService,
    StageResult,
    _StageAttemptResult,
)
from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
from rflp_lite.application.tool_layer import ToolResult
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
from rflp_lite.methodology.controller import ControllerAction, ControllerPlan
from rflp_lite.methodology.llm_controller import LLMController
from rflp_lite.methodology.vertical_coverage import resolve_requirement_trace
from rflp_lite.methodology.vertical_generation import stage_spec, stage_task
from rflp_lite.ports.generative_model import GenerationResponse
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


class ScriptedModel:
    def __init__(self):
        self.calls = []
        self.relation_contexts = []
        self.controller_decisions = []
        self.evidence_contexts = []
        self.methodology_guidances = []
        self.context_token_estimates = []

    def complete_json(self, request):
        self.calls.append(request.lens_id)
        self.relation_contexts.append(request.user_payload["context"]["relations"])
        self.controller_decisions.append(request.user_payload["controller_decisions"])
        self.evidence_contexts.append(request.user_payload["evidence"])
        self.methodology_guidances.append(request.user_payload["methodology_guidance"])
        self.context_token_estimates.append(
            request.user_payload["context"]["token_estimate"]
        )
        entities = request.user_payload["context"]["entities"]
        by_kind = {}
        for item in entities:
            by_kind.setdefault(item["kind"], []).append(item)
        payload = {"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": request.lens_id}

        def entity(local_ref, kind, name, data):
            payload["entities"].append({"local_ref": local_ref, "kind": kind, "name": name, "payload": data, "confidence": 0.9, "source_ids": [], "evidence_ids": [], "lifecycle_ids": []})

        def relation(source_ref, predicate, target_ref):
            payload["relations"].append({"source_ref": source_ref, "predicate": predicate, "target_ref": target_ref, "evidence_ids": []})

        required_by_lens = {
            "vertical.requirements": {
                "system", "stakeholder", "concern", "lifecycle_stage",
                "lifecycle_transition", "scenario_hypothesis", "use_case",
                "operational_scenario", "activity", "requirement",
            },
            "vertical.functional": {"function"},
            "vertical.logical": {"logical_component", "interface", "state"},
            "vertical.physical": {"physical_block"},
            "vertical.verification_validation": {
                "verification_case", "validation_case", "hazard", "failure_mode",
            },
        }
        if required_by_lens.get(request.lens_id, set()) <= set(by_kind):
            payload["assumptions"] = ["脚本模型用于测试结构化边界"]
            payload["open_questions"] = []
            payload["decision_records"] = [{
                "step": request.lens_id,
                "decision": "按照阶段契约产生结构化模型",
                "basis": [],
            }]
            return GenerationResponse(request.lens_id, payload, "input", "output", False, "fake", "scripted")

        requirements = by_kind.get("requirement", [])
        if request.lens_id == "vertical.requirements":
            entity("system", "system", "校园配送系统", {"mission": "完成校园配送", "system_boundary": {"inside": ["配送服务"], "outside": ["校园环境"]}, "objectives": ["按时完成任务"], "environment_assumptions": ["道路可通行"], "exclusions": [], "open_questions": []})
            entity("stakeholder", "stakeholder", "配送运营人员", {"role": "任务运营"})
            entity("concern", "concern", "任务可靠性与运营可用性", {"topic": "异常场景下任务仍可追踪"})
            entity("lifecycle", "lifecycle_stage", "设计—运行生命周期", {"stage": "operation", "sequence": ["设计", "部署", "运行", "维护"]})
            entity("transition", "lifecycle_transition", "部署到运行", {"from_stage": "部署", "to_stage": "运行", "trigger": "部署验收完成", "guard": "运行环境可用"})
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
            relation("transition", "derivedFrom", "lifecycle")
            if requirements:
                relation(requirements[0]["id"], "derivedFrom", "activity")
        elif request.lens_id == "vertical.functional":
            entity("function", "function", "规划并执行配送", {"behavior": "根据任务完成配送", "inputs": ["任务"], "outputs": ["结果"], "decomposition": ["解析任务", "执行配送", "反馈结果"]})
            entity("flow", "functional_flow", "任务结果流", {
                "source_function_ids": ["function"],
                "target_function_ids": ["function"],
                "content": "任务和结果",
            })
            entity("fscenario", "functional_scenario", "完成配送功能场景", {"function_ids": ["function"], "steps": ["输入", "处理", "输出"]})
            if requirements:
                relation(requirements[0]["id"], "satisfiedBy", "function")
            relation("function", "exchangesWith", "flow")
        elif request.lens_id == "vertical.logical":
            functions = by_kind.get("function", [])
            entity("logical", "logical_component", "配送控制组件", {
                "responsibility": "协调配送功能",
                "architecture_rationale": "按配送职责形成逻辑分区",
                "interfaces": [],
            })
            entity("interface", "interface", "配送服务接口", {"protocol": "logical-message", "exchanges": ["request", "response"]})
            entity("state", "state", "配送任务状态", {"values": ["待受理", "执行中", "人工接管", "完成", "失败"], "transitions": ["待受理->执行中", "执行中->完成"]})
            if functions:
                relation(functions[0]["id"], "allocatedTo", "logical")
                relation(functions[0]["id"], "exchangesWith", "interface")
            relation("logical", "decomposes", "state")
        elif request.lens_id == "vertical.physical":
            entity("physical", "physical_block", "配送执行单元", {
                "candidate_type": "可部署执行单元",
                "selection_rationale": "选择能够承载逻辑职责的物理候选",
                "constraints": ["满足逻辑职责"],
                "rationale": "承载配送控制",
            })
            logical = by_kind.get("logical_component", [])
            if logical:
                relation(logical[0]["id"], "allocatedTo", "physical")
        elif request.lens_id == "vertical.verification_validation":
            trace_scope = {
                "requirement_ids": [requirements[0]["id"]] if requirements else [],
                "function_ids": [item["id"] for item in by_kind.get("function", [])],
                "logical_component_ids": [item["id"] for item in by_kind.get("logical_component", [])],
                "physical_ids": [item["id"] for item in by_kind.get("physical_block", [])],
            }
            entity("verification", "verification_case", "验证配送需求", {"method": "test", "verification_objective": "证明配送需求满足", "precondition": "系统处于可测试初始状态", "test_condition": "标准运行环境、额定负载和需求边界条件", "input": "配送任务", "stimulus": "提交配送任务并施加人工接管事件", "procedure": "执行测试步骤并记录实际结果", "expected_result": "实际结果满足需求目标", "pass_criteria": "测试结果满足需求", **trace_scope, "scenario_ids": [], "activity_ids": [], "covered_branches": ["人工接管"], "evidence_ids": []})
            entity("validation", "validation_case", "确认配送体验", {"method": "demonstration", "verification_objective": "确认用户场景目标达成", "precondition": "目标用户和典型场景可用", "test_condition": "典型用户、真实运行场景和代表性任务条件", "input": "配送任务", "stimulus": "由运营人员执行配送并触发必要的用户操作", "procedure": "在典型场景执行并收集用户反馈", "expected_result": "用户场景目标达成", "pass_criteria": "用户场景确认通过", **trace_scope, "scenario_ids": [], "activity_ids": [], "covered_branches": ["人工接管"], "evidence_ids": []})
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


class TransportFailingVerticalRuntime:
    def __init__(self):
        self.model = ScriptedModel()
        self.model.automatic_vertical_stage_feedback = False
        self._delegate = StructuredModelRuntime(self.model)

    def execute(self, request):
        if request.task_id == "vertical.verification_validation":
            return TaskExecutionResponse(
                StepStatus.DEGRADED,
                diagnostics=("remote connection reset",),
            )
        return self._delegate.execute(request)


class ControllerProposalModel:
    supports_controller_proposals = True

    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def complete_json(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        action = request.user_payload["controller_plan"]["actions"][0]
        option_id = action["options"][0]["id"] if action["options"] else None
        return GenerationResponse(
            request.lens_id,
            {
                "action_id": action["id"],
                "option_id": option_id,
                "rationale": "先处理当前最高优先级的工程缺口。",
                "assumptions": ["当前确定性检查结果仍然有效"],
                "open_questions": [],
            },
            "controller-input",
            "controller-output",
            False,
            "fake-controller",
            "remote-test-model",
        )


def test_prepare_generation_creates_persisted_run_without_executing_runtime(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")

    run_id = generation.prepare_generation(
        "robot",
        requirement_text="系统应支持人工接管",
        run_id="web-run-prepared",
    )

    run = services.repository("robot").load_run("robot", run_id)
    assert run_id == "web-run-prepared"
    assert run is not None
    assert run.status == "running"
    assert sorted(step.task_id for step in run.steps) == sorted([
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ])
    assert services.model("robot").graph("robot").revision == 1


class SemanticInvalidModel(ScriptedModel):
    def complete_json(self, request):
        response = super().complete_json(request)
        if request.lens_id == "vertical.functional" and response.payload["entities"]:
            response.payload["entities"][0]["name"] = "搭载传感器与计算通信模块"
        return response


class MissingRequirementObligationModel(ScriptedModel):
    def complete_json(self, request):
        response = super().complete_json(request)
        if request.lens_id == "vertical.requirements":
            for entity in response.payload.get("entities", []):
                if entity.get("kind") == EntityKind.REQUIREMENT.value:
                    entity.setdefault("payload", {}).pop("obligation", None)
        return response


class FeedbackFunctionalModel(ScriptedModel):
    def __init__(self):
        super().__init__()
        self.functional_attempts = 0
        self.functional_context_revisions = []

    def complete_json(self, request):
        if request.lens_id == "vertical.functional":
            self.functional_context_revisions.append(request.user_payload["context"]["revision"])
        response = super().complete_json(request)
        if request.lens_id == "vertical.functional":
            self.functional_attempts += 1
            if self.functional_attempts == 2:
                context_entities = request.user_payload["context"]["entities"]
                requirement = next(
                    item for item in context_entities if item["kind"] == "requirement"
                )
                function = next(
                    item for item in context_entities if item["kind"] == "function"
                )
                response.payload["entities"] = []
                response.payload["relations"] = []
                response.payload["updates"] = [{
                    "entity_id": requirement["id"],
                    "field_patch": {
                        "payload": {
                            "functional_behavior_ids": [function["id"]],
                            "functional_requirement_status": "allocated",
                        },
                    },
                }]
        return response


class CompleteVerticalModel(ScriptedModel):
    """Deterministic stand-in for one complete structured remote-model run."""

    def complete_json(self, request):
        recorded = super().complete_json(request)
        return replace(recorded, payload=self._proposal(request))

    def _proposal(self, request):
        context = request.user_payload["context"]["entities"]
        by_kind = {}
        for item in context:
            by_kind.setdefault(item["kind"], []).append(item)
        payload = {
            "entities": [],
            "relations": [],
            "updates": [],
            "deprecations": [],
            "reason": f"完成 {request.lens_id} 的结构化建模",
            "assumptions": ["结构化夹具只表达可由当前 ModelGraph 证明的工程事实"],
            "open_questions": [],
            "decision_records": [{
                "step": request.lens_id,
                "decision": "沿当前上下文补齐本阶段的可追溯模型元素",
                "basis": [item["id"] for item in context[:3]],
            }],
        }

        def entity(local_ref, kind, name, data):
            payload["entities"].append({
                "local_ref": local_ref,
                "kind": kind,
                "name": name,
                "payload": data,
                "confidence": 0.95,
                "source_ids": [],
                "evidence_ids": [],
                "lifecycle_ids": [],
            })

        def relation(source_ref, predicate, target_ref):
            payload["relations"].append({
                "source_ref": source_ref,
                "predicate": predicate,
                "target_ref": target_ref,
                "evidence_ids": [],
            })

        def update(entity_id, data):
            payload["updates"].append({
                "entity_id": entity_id,
                "field_patch": {"payload": data},
            })

        requirement = by_kind[EntityKind.REQUIREMENT.value][0]
        requirement_id = requirement["id"]
        if request.lens_id == "vertical.requirements":
            entity(
                "system-1", "system", "校园配送系统",
                {
                    "mission": "在校园内完成可追踪配送",
                    "system_boundary": {
                        "inside": ["配送服务能力"],
                        "outside": ["校园道路环境"],
                    },
                    "objectives": ["按时完成配送", "异常时支持人工接管"],
                    "environment_assumptions": ["校园网络和道路可用"],
                    "exclusions": ["不预设具体硬件厂商"],
                    "open_questions": [],
                },
            )
            entity(
                "stakeholder-1", "stakeholder", "配送运营人员",
                {"role": "任务运营", "goal": "掌握任务状态并处理异常"},
            )
            entity(
                "concern-1", "concern", "任务可靠性与运营可用性",
                {
                    "topic": "异常场景下任务仍可追踪",
                    "description": "异常时运营人员可以识别状态并接管任务",
                    "type": "operational_goal",
                    "goal": "保持任务闭环",
                    "rationale": "来自用户输入中的人工接管目标",
                },
            )
            entity(
                "lifecycle-1", "lifecycle_stage", "设计到运行生命周期",
                {"stage": "operation", "sequence": ["设计", "部署", "运行", "维护"]},
            )
            entity(
                "transition-1", "lifecycle_transition", "部署到运行",
                {"from_stage": "部署", "to_stage": "运行", "trigger": "部署验收完成"},
            )
            entity(
                "hypothesis-1", "scenario_hypothesis", "典型校园配送场景",
                {"category": "normal", "trigger": "提交配送任务", "outcome": "任务完成"},
            )
            entity(
                "use-case-1", "use_case", "执行一次校园配送任务",
                {"primary_actor": "配送运营人员", "goal": "完成可追踪配送"},
            )
            entity(
                "scenario-1", "operational_scenario", "典型配送操作场景",
                {
                    "actor_ids": ["stakeholder-1"],
                    "steps": ["提交任务", "执行配送", "人工接管或完成"],
                    "exchanges": ["任务请求", "状态反馈"],
                    "internal_component_ids": [],
                },
            )
            entity(
                "activity-1", "activity", "受理并完成配送活动",
                {
                    "steps": ["受理任务", "执行配送", "反馈结果"],
                    "branches": ["人工接管"],
                    "goal": "完成配送并反馈任务状态",
                },
            )
            update(requirement_id, {
                "stakeholder_ids": ["stakeholder-1"],
                "derived_by": "system_requirement_derivation",
            })
            relation("system-1", "decomposes", "stakeholder-1")
            relation("stakeholder-1", "hasConcern", "concern-1")
            relation("stakeholder-1", "participatesIn", "scenario-1")
            relation("use-case-1", "derivedFrom", "hypothesis-1")
            relation("scenario-1", "derivedFrom", "use-case-1")
            relation("activity-1", "occursIn", "lifecycle-1")
            relation("transition-1", "derivedFrom", "lifecycle-1")
            relation(requirement_id, "derivedFrom", "concern-1")
        elif request.lens_id == "vertical.functional":
            entity(
                "function-1", "function", "规划并执行配送",
                {
                    "behavior": "根据任务完成配送并反馈状态",
                    "inputs": ["配送任务"],
                    "outputs": ["配送结果", "任务状态"],
                    "decomposition": "解析任务、规划路径、执行配送、反馈结果",
                    "logical_partition": "配送控制",
                },
            )
            entity(
                "flow-1", "functional_flow", "任务与结果流",
                {
                    "source_function_ids": ["function-1"],
                    "target_function_ids": ["function-1"],
                    "content": "任务请求、路径信息和状态反馈",
                },
            )
            entity(
                "fscenario-1", "functional_scenario", "完成配送功能场景",
                {
                    "function_ids": ["function-1"],
                    "steps": ["接收任务", "规划并执行", "反馈结果"],
                },
            )
            update(requirement_id, {
                "functional_behavior_ids": ["function-1"],
                "functional_requirement_status": "allocated",
            })
            relation(requirement_id, "satisfiedBy", "function-1")
            relation("function-1", "exchangesWith", "flow-1")
        elif request.lens_id == "vertical.logical":
            entity(
                "logical-1", "logical_component", "配送控制组件",
                {
                    "responsibility": "协调配送功能、状态和人工接管",
                    "partition_basis": "按配送控制职责形成逻辑分区",
                    "functional_flow_ids": [
                        item["id"] for item in by_kind.get(EntityKind.FUNCTIONAL_FLOW.value, [])
                    ],
                    "shared_state_ids": ["state-1"],
                    "dependencies": [],
                    "cohesion": "high",
                    "coupling": "low",
                    "architecture_rationale": "单一逻辑组件承载当前配送功能，保持职责闭合",
                },
            )
            entity(
                "interface-1", "interface", "配送任务交互接口",
                {
                    "protocol": "logical-message",
                    "exchanges": ["task_request", "task_status", "handover"],
                    "connected_component_ids": ["logical-1"],
                },
            )
            entity(
                "state-1", "state", "配送任务状态",
                {
                    "values": ["待受理", "执行中", "人工接管", "完成", "失败"],
                    "transitions": ["待受理->执行中", "执行中->完成", "执行中->人工接管"],
                    "owner_id": "logical-1",
                },
            )
            function_ids = [item["id"] for item in by_kind.get(EntityKind.FUNCTION.value, [])]
            for function_id in function_ids:
                relation(function_id, "allocatedTo", "logical-1")
                relation(function_id, "exchangesWith", "interface-1")
            relation("logical-1", "connectedTo", "interface-1")
            relation("logical-1", "decomposes", "state-1")
        elif request.lens_id == "vertical.physical":
            logical = by_kind[EntityKind.LOGICAL_COMPONENT.value][0]
            functions = by_kind.get(EntityKind.FUNCTION.value, [])
            function_ids = [item["id"] for item in functions]
            decision = self._controller_decision(request)
            selected_option = str(decision.get("option", "")).strip()
            if selected_option == "更换物理候选或计算架构":
                name = "配送执行单元替代方案"
                candidate_id = make_entity(EntityKind.PHYSICAL_BLOCK, name).id
                entity(
                    "physical-alternative", "physical_block", name,
                    self._physical_payload(
                        logical["id"], function_ids, requirement_id, candidate_id,
                        decision=decision,
                        alternative=True,
                    ),
                )
                relation(logical["id"], "allocatedTo", "physical-alternative")
                relation(requirement_id, "satisfiedBy", "physical-alternative")
            else:
                entity(
                    "physical-1", "physical_block", "配送执行单元",
                    self._physical_payload(
                        logical["id"], function_ids, requirement_id,
                        make_entity(EntityKind.PHYSICAL_BLOCK, "配送执行单元").id,
                    ),
                )
                relation(logical["id"], "allocatedTo", "physical-1")
            if selected_option != "更换物理候选或计算架构":
                update(requirement_id, {
                    "feasibility_review": {
                        "status": "reviewed",
                        "measured_values": {"status": "not_executed"},
                        "physical_candidate_ids": ["physical-1"],
                    },
                })
        elif request.lens_id == "vertical.verification_validation":
            requirements = by_kind.get(EntityKind.REQUIREMENT.value, [])
            functions = by_kind.get(EntityKind.FUNCTION.value, [])
            logicals = by_kind.get(EntityKind.LOGICAL_COMPONENT.value, [])
            physicals = by_kind.get(EntityKind.PHYSICAL_BLOCK.value, [])
            activities = by_kind.get(EntityKind.ACTIVITY.value, [])
            scenarios = (
                by_kind.get(EntityKind.OPERATIONAL_SCENARIO.value, [])
                + by_kind.get(EntityKind.FUNCTIONAL_SCENARIO.value, [])
            )
            scope = {
                "requirement_ids": [item["id"] for item in requirements],
                "function_ids": [item["id"] for item in functions],
                "logical_component_ids": [item["id"] for item in logicals],
                "physical_ids": [item["id"] for item in physicals],
            }
            activity_ids = [item["id"] for item in activities]
            scenario_ids = [item["id"] for item in scenarios]
            branches = ["人工接管"] if activity_ids else []
            existing_verifications = by_kind.get(EntityKind.VERIFICATION_CASE.value, [])
            existing_validations = by_kind.get(EntityKind.VALIDATION_CASE.value, [])
            if existing_verifications or existing_validations:
                for item in existing_verifications:
                    update(item["id"], {
                        **scope,
                        "cross_analysis_status": "checked",
                        "traceability_checked": True,
                    })
                for item in existing_validations:
                    update(item["id"], scope)
            else:
                entity(
                    "verification-1", "verification_case", "验证配送需求",
                    {
                        **scope,
                        "method": "test",
                        "test_condition": "标准运行环境、额定负载和需求边界条件",
                        "stimulus": "提交配送任务并施加正常、失败和人工接管事件",
                        "precondition": "系统处于可测试初始状态",
                        "input": "配送任务和人工接管指令",
                        "procedure": "执行正常、失败和人工接管分支并记录结果",
                        "expected_result": "任务完成或人工接管后状态保持可追踪",
                        "pass_criteria": "所有步骤满足需求并保留结果记录",
                        "scenario_ids": scenario_ids,
                        "activity_ids": activity_ids,
                        "covered_branches": branches,
                        "evidence_ids": [],
                        "execution_evidence_ids": [],
                        "verification_objective": "验证配送功能和人工接管要求",
                        "constraint_fields": [],
                        "evidence_required": False,
                        "open_questions": ["尚未执行真实测试"],
                        "cross_analysis_status": "checked",
                        "traceability_checked": True,
                    },
                )
                entity(
                    "validation-1", "validation_case", "确认配送使用场景",
                    {
                        **scope,
                        "method": "demonstration",
                        "test_condition": "典型用户、真实运行场景和代表性任务条件",
                        "stimulus": "由运营人员执行配送并触发必要的用户操作",
                        "precondition": "目标用户和典型配送场景可用",
                        "input": "真实配送任务和用户接管操作",
                        "procedure": "邀请运营人员执行典型场景并确认任务体验",
                        "expected_result": "运营人员确认任务状态清晰且可在异常时接管",
                        "pass_criteria": "用户确认场景目标达成",
                        "scenario_ids": scenario_ids,
                        "activity_ids": activity_ids,
                        "covered_branches": branches,
                        "evidence_ids": [],
                        "execution_evidence_ids": [],
                        "verification_objective": "确认典型场景满足用户目标",
                        "constraint_fields": [],
                        "evidence_required": False,
                        "open_questions": ["尚未执行真实用户确认"],
                    },
                )
                entity(
                    "hazard-1", "hazard", "风险：配送任务未完成",
                    {
                        "description": "执行条件异常或人工接管失败导致任务目标未达成",
                        "requirement_ids": [requirement_id],
                        "activity_ids": activity_ids,
                        "branches": branches,
                    },
                )
                entity(
                    "failure-1", "failure_mode", "失效模式：任务状态丢失",
                    {
                        "effect": "运营人员无法确认任务状态",
                        "cause": "异常分支未写入可追踪状态",
                        "requirement_ids": [requirement_id],
                        "activity_ids": activity_ids,
                    },
                )
                relation(requirement_id, "verifiedBy", "verification-1")
                relation(requirement_id, "validatedBy", "validation-1")
                relation("hazard-1", "derivedFrom", requirement_id)
                relation("hazard-1", "causes", "failure-1")
                relation("hazard-1", "mitigatedBy", "verification-1")
                relation("failure-1", "mitigatedBy", "verification-1")
            if not existing_verifications:
                update(requirement_id, {
                    "feasibility_review": {
                        "status": "reviewed",
                        "physical_candidate_ids": [item["id"] for item in physicals],
                    },
                })
        return payload

    @staticmethod
    def _controller_decision(request):
        decisions = request.user_payload.get("controller_decisions", [])
        return decisions[-1] if decisions and isinstance(decisions[-1], dict) else {}

    @staticmethod
    def _physical_payload(logical_id, function_ids, requirement_id, physical_id, *, decision=None, alternative=False):
        impact_chain = {
            "requirement_ids": [requirement_id],
            "function_ids": list(function_ids),
            "logical_ids": [logical_id],
            "physical_ids": [physical_id],
        }
        payload = {
            "candidate_type": "可部署配送执行单元",
            "vendor": "工程候选",
            "part_number": "候选方案-A" if not alternative else "候选方案-B",
            "constraints": ["满足配送控制逻辑职责"],
            "constraint_provenance": [],
            "logical_id": logical_id,
            "measurement_status": "design_estimate",
            "technical_requirement_status": "no_explicit_constraints",
            "trade_study": {
                "alternatives": ["集中式执行单元", "分布式执行单元"],
                "selection_rationale": "按当前逻辑职责选择可部署执行单元",
                "decision_status": "selected" if alternative else "baseline",
            },
            "source_logical_ids": [logical_id],
            "source_function_ids": list(function_ids),
            "source_requirement_ids": [requirement_id],
            "propagated_constraints": {},
            "propagated_constraint_provenance": [],
            "impact_chain": impact_chain,
            "resolution_options": [],
            "feasibility": {
                "status": "feasible",
                "checks": ["mass", "power", "compute", "memory", "latency"],
            },
            "alternatives": ["集中式执行单元", "分布式执行单元"],
            "selection_rationale": "保持逻辑职责完整并满足当前任务目标",
            "rationale": "承载配送控制逻辑",
            "mass_kg": 12.0,
            "power_w": 40.0,
            "compute": 8.0,
            "memory_mb": 2048.0,
            "latency_ms": 50.0,
            "bandwidth_mbps": 100.0,
            "cost": 5000.0,
            "thermal": "nominal",
            "reliability": "0.99",
            "availability": "0.98",
            "endurance_h": 12.0,
        }
        if alternative:
            payload.update({
                "candidate_variant": "alternative",
                "architecture_decision": dict(decision or {}),
                "open_questions": ["替代方案仍需实际部署验证"],
            })
        return payload


class IntakeAwareCompleteVerticalModel(CompleteVerticalModel):
    """One provider double for both structured intake and vertical stages."""

    supports_requirements_intake = True

    def __init__(self):
        super().__init__()
        self.intake_requests = []
        self.intake_source_ref = ""
        self.intake_document_id = ""

    def complete_json(self, request):
        if request.lens_id == "requirements.use_case":
            self.calls.append(request.lens_id)
            self.intake_requests.append(request)
            self.intake_source_ref = request.user_payload["source_refs"][0]
            self.intake_document_id = request.user_payload["source_regions"][0]["document_id"]
            source_ref = self.intake_source_ref
            document_id = self.intake_document_id
            return GenerationResponse(
                request.lens_id,
                {
                    "schema_version": "requirements-use-case-draft.v1",
                    "source_document_ids": [document_id],
                    "system_context": {
                        "name": "校园配送系统",
                        "mission": "完成校园配送",
                        "attributes": {
                            "platform_type": "robot",
                            "capture_source": "llm",
                        },
                        "source_refs": [source_ref],
                    },
                    "entities": [{
                        "local_ref": "actor_operator",
                        "kind": "stakeholder",
                        "name": "配送运营人员",
                        "attributes": {"role": "任务运营"},
                        "source_refs": [source_ref],
                        "confidence": 0.9,
                    }],
                    "requirements": [{
                        "local_ref": "requirement_delivery",
                        "statement": "系统应完成校园配送",
                        "level": "system",
                        "type": "functional",
                        "obligation": "系统应",
                        "verification_method": "test",
                        "constraints": [],
                        "source_refs": [source_ref],
                        "confidence": 0.9,
                        "related_refs": [],
                    }],
                    "use_cases": [{
                        "local_ref": "use_case_delivery",
                        "name": "执行配送",
                        "goal": "完成校园配送",
                        "primary_actor_refs": ["actor_operator"],
                        "preconditions": [],
                        "postconditions": [],
                        "scenario_refs": ["scenario_delivery"],
                        "requirement_refs": ["requirement_delivery"],
                        "source_refs": [source_ref],
                        "confidence": 0.9,
                    }],
                    "scenarios": [{
                        "local_ref": "scenario_delivery",
                        "kind": "operational_scenario",
                        "name": "校园配送场景",
                        "description": "运营人员提交任务并完成配送",
                        "actor_refs": ["actor_operator"],
                        "steps": [{
                            "order": 1,
                            "actor_ref": "actor_operator",
                            "action": "提交配送任务",
                            "guard": "",
                        }],
                        "branches": [],
                        "requirement_refs": ["requirement_delivery"],
                        "source_refs": [source_ref],
                        "confidence": 0.9,
                    }],
                    "clarifications": [],
                    "diagnostics": [],
                },
                "intake-input",
                "intake-output",
                False,
                "fake-intake-provider",
                "intake-aware-test-model",
            )
        if request.lens_id == "vertical.requirements":
            response = super().complete_json(request)
            context_entities = request.user_payload["context"]["entities"]
            active_ids_by_kind = {}
            for item in context_entities:
                active_ids_by_kind.setdefault(item["kind"], []).append(item["id"])
            local_to_existing = {}
            filtered_entities = []
            for item in response.payload["entities"]:
                existing_ids = active_ids_by_kind.get(item["kind"], [])
                if existing_ids:
                    local_to_existing[item["local_ref"]] = existing_ids[0]
                else:
                    filtered_entities.append(item)
            filtered_relations = []
            for relation in response.payload["relations"]:
                filtered_relations.append({
                    **relation,
                    "source_ref": local_to_existing.get(
                        relation["source_ref"], relation["source_ref"]
                    ),
                    "target_ref": local_to_existing.get(
                        relation["target_ref"], relation["target_ref"]
                    ),
                })
            def rewrite_reference(value):
                if isinstance(value, str):
                    return local_to_existing.get(value, value)
                if isinstance(value, list):
                    return [rewrite_reference(item) for item in value]
                if isinstance(value, dict):
                    return {key: rewrite_reference(item) for key, item in value.items()}
                return value

            filtered_updates = [
                {
                    **update,
                    "field_patch": rewrite_reference(update.get("field_patch", {})),
                }
                for update in response.payload["updates"]
            ]
            return replace(
                response,
                payload={
                    **response.payload,
                    "entities": filtered_entities,
                    "relations": filtered_relations,
                    "updates": filtered_updates,
                },
            )
        return super().complete_json(request)


class TwoRequirementFeedbackModel(CompleteVerticalModel):
    """Structured model double that repairs the second requirement on feedback."""

    def __init__(self):
        super().__init__()
        self.functional_attempts = 0
        self.functional_guidances = []

    def complete_json(self, request):
        if request.lens_id == "vertical.functional":
            self.functional_attempts += 1
            self.functional_guidances.append(
                request.user_payload["methodology_guidance"]
            )
            if self.functional_attempts == 2:
                return GenerationResponse(
                    request.lens_id,
                    self._missing_function_proposal(request),
                    "input",
                    "feedback-output",
                    False,
                    "fake",
                    "scripted",
                )
        if request.lens_id == "vertical.verification_validation":
            return GenerationResponse(
                request.lens_id,
                self._assurance_proposal(request),
                "input",
                "assurance-output",
                False,
                "fake",
                "scripted",
            )
        return super().complete_json(request)

    @staticmethod
    def _context_by_kind(request):
        values = {}
        for item in request.user_payload["context"]["entities"]:
            values.setdefault(item["kind"], []).append(item)
        return values

    @staticmethod
    def _relation_targets(request, source_id, predicate, target_kind=None):
        result = []
        for relation in request.user_payload["context"]["relations"]:
            if relation["source_id"] != source_id or relation["predicate"] != predicate:
                continue
            if target_kind is not None:
                target = next(
                    (
                        item
                        for item in request.user_payload["context"]["entities"]
                        if item["id"] == relation["target_id"]
                    ),
                    None,
                )
                if target is None or target["kind"] != target_kind:
                    continue
            result.append(relation["target_id"])
        return tuple(sorted(set(result)))

    def _missing_function_proposal(self, request):
        by_kind = self._context_by_kind(request)
        requirements = by_kind[EntityKind.REQUIREMENT.value]
        existing_function_sources = {
            relation["source_id"]
            for relation in request.user_payload["context"]["relations"]
            if relation["predicate"] == RelationPredicate.SATISFIED_BY.value
            and relation["source_id"] in {item["id"] for item in requirements}
            and relation["target_id"] in {
                item["id"] for item in by_kind.get(EntityKind.FUNCTION.value, [])
            }
        }
        requirement = next(
            item for item in requirements if item["id"] not in existing_function_sources
        )
        flow = by_kind[EntityKind.FUNCTIONAL_FLOW.value][0]
        function_ref = "function-feedback-2"
        return {
            "entities": [{
                "local_ref": function_ref,
                "kind": EntityKind.FUNCTION.value,
                "name": f"执行：{requirement['name']}",
                "payload": {
                    "behavior": f"实现{requirement['name']}",
                    "inputs": ["任务"],
                    "outputs": ["结果"],
                    "decomposition": ["解析需求", "执行行为", "反馈结果"],
                    "source_requirement_id": requirement["id"],
                },
                "confidence": 0.95,
                "source_ids": [],
                "evidence_ids": [],
                "lifecycle_ids": [],
            }],
            "relations": [
                {
                    "source_ref": requirement["id"],
                    "predicate": RelationPredicate.SATISFIED_BY.value,
                    "target_ref": function_ref,
                    "evidence_ids": [],
                },
                {
                    "source_ref": function_ref,
                    "predicate": RelationPredicate.EXCHANGES_WITH.value,
                    "target_ref": flow["id"],
                    "evidence_ids": [],
                },
            ],
            "updates": [{
                "entity_id": requirement["id"],
                "field_patch": {"payload": {
                    "functional_behavior_ids": [function_ref],
                    "functional_requirement_status": "allocated",
                }},
            }],
            "deprecations": [],
            "reason": "根据逐需求 coverage feedback 补齐缺失功能",
            "assumptions": [],
            "open_questions": [],
            "decision_records": [{
                "step": "requirement_coverage_feedback",
                "decision": "补齐反馈中列出的第二条需求功能",
                "basis": [requirement["id"]],
            }],
        }

    def _assurance_proposal(self, request):
        by_kind = self._context_by_kind(request)
        requirements = by_kind[EntityKind.REQUIREMENT.value]
        activities = by_kind.get(EntityKind.ACTIVITY.value, [])
        scenarios = (
            by_kind.get(EntityKind.OPERATIONAL_SCENARIO.value, [])
            + by_kind.get(EntityKind.FUNCTIONAL_SCENARIO.value, [])
        )
        proposal = {
            "entities": [],
            "relations": [],
            "updates": [],
            "deprecations": [],
            "reason": "为每条需求建立独立且作用域一致的 V&V 计划",
            "assumptions": [],
            "open_questions": [],
            "decision_records": [{
                "step": "verification_validation",
                "decision": "逐条需求检查 verification 和 validation coverage",
                "basis": [item["id"] for item in requirements],
            }],
        }

        def add(local_ref, kind, name, payload):
            proposal["entities"].append({
                "local_ref": local_ref,
                "kind": kind,
                "name": name,
                "payload": payload,
                "confidence": 0.95,
                "source_ids": [],
                "evidence_ids": [],
                "lifecycle_ids": [],
            })

        def relate(source_ref, predicate, target_ref):
            proposal["relations"].append({
                "source_ref": source_ref,
                "predicate": predicate,
                "target_ref": target_ref,
                "evidence_ids": [],
            })

        def update(entity_id, payload):
            proposal["updates"].append({
                "entity_id": entity_id,
                "field_patch": {"payload": payload},
            })

        all_requirement_ids = [item["id"] for item in requirements]
        for index, requirement in enumerate(requirements, start=1):
            function_ids = self._relation_targets(
                request,
                requirement["id"],
                RelationPredicate.SATISFIED_BY.value,
                EntityKind.FUNCTION.value,
            )
            logical_ids = tuple(sorted({
                logical_id
                for function_id in function_ids
                for logical_id in self._relation_targets(
                    request,
                    function_id,
                    RelationPredicate.ALLOCATED_TO.value,
                    EntityKind.LOGICAL_COMPONENT.value,
                )
            }))
            physical_ids = tuple(sorted({
                physical_id
                for logical_id in logical_ids
                for physical_id in self._relation_targets(
                    request,
                    logical_id,
                    RelationPredicate.ALLOCATED_TO.value,
                    EntityKind.PHYSICAL_BLOCK.value,
                )
            }))
            scope = {
                "requirement_ids": [requirement["id"]],
                "function_ids": list(function_ids),
                "logical_component_ids": list(logical_ids),
                "physical_ids": list(physical_ids),
            }
            verification_ref = f"verification-feedback-{index}"
            validation_ref = f"validation-feedback-{index}"
            shared = {
                **scope,
                "test_condition": "标准运行环境、额定负载和需求边界条件",
                "stimulus": "提交需求并执行正常、异常及人工接管事件",
                "precondition": "系统处于可测试状态",
                "input": requirement["name"],
                "procedure": "执行需求场景并记录结果",
                "expected_result": "系统行为满足需求",
                "pass_criteria": "结果满足需求义务",
                "scenario_ids": [item["id"] for item in scenarios],
                "activity_ids": [item["id"] for item in activities],
                "covered_branches": ["人工接管"] if activities else [],
                "evidence_ids": [],
                "execution_evidence_ids": [],
                "verification_objective": f"检查{requirement['name']}",
                "constraint_fields": [],
                "evidence_required": False,
                "open_questions": ["尚未执行真实测试"],
            }
            add(
                verification_ref,
                EntityKind.VERIFICATION_CASE.value,
                f"验证：{requirement['name']}",
                {**shared, "method": "test", "cross_analysis_status": "checked", "traceability_checked": True},
            )
            add(
                validation_ref,
                EntityKind.VALIDATION_CASE.value,
                f"确认：{requirement['name']}",
                {**shared, "method": "demonstration"},
            )
            relate(requirement["id"], RelationPredicate.VERIFIED_BY.value, verification_ref)
            relate(requirement["id"], RelationPredicate.VALIDATED_BY.value, validation_ref)
            update(requirement["id"], {
                "feasibility_review": {
                    "status": "reviewed",
                    "physical_candidate_ids": list(physical_ids),
                },
            })

        hazard_ref = "hazard-feedback"
        failure_ref = "failure-feedback"
        first_requirement_id = all_requirement_ids[0]
        add(
            hazard_ref,
            EntityKind.HAZARD.value,
            "风险：需求目标未达成",
            {
                "description": "异常分支导致一项或多项需求目标未达成",
                "requirement_ids": all_requirement_ids,
                "activity_ids": [item["id"] for item in activities],
                "branches": ["人工接管"] if activities else [],
            },
        )
        add(
            failure_ref,
            EntityKind.FAILURE_MODE.value,
            "失效模式：任务结果不可追踪",
            {
                "effect": "需求结果不满足",
                "cause": "异常处理未形成可追踪结果",
                "requirement_ids": all_requirement_ids,
                "activity_ids": [item["id"] for item in activities],
            },
        )
        relate(hazard_ref, RelationPredicate.CAUSES.value, failure_ref)
        relate(hazard_ref, RelationPredicate.DERIVED_FROM.value, first_requirement_id)
        relate(hazard_ref, RelationPredicate.MITIGATED_BY.value, "verification-feedback-1")
        relate(failure_ref, RelationPredicate.MITIGATED_BY.value, "verification-feedback-1")
        return proposal


class ThreeRequirementStructuredModel(TwoRequirementFeedbackModel):
    """Structured model double that covers every input requirement in one run."""

    def __init__(self):
        super().__init__()
        self.requirement_worklists = []

    def complete_json(self, request):
        self.requirement_worklists.append(
            request.user_payload.get("requirement_worklist", [])
        )
        recorded = ScriptedModel.complete_json(self, request)
        if request.lens_id == "vertical.functional":
            return replace(recorded, payload=self._multi_requirement_functional(request))
        if request.lens_id == "vertical.verification_validation":
            return replace(recorded, payload=self._assurance_proposal(request))
        return replace(recorded, payload=CompleteVerticalModel._proposal(self, request))

    @staticmethod
    def _multi_requirement_functional(request):
        requirements = [
            item
            for item in request.user_payload["context"]["entities"]
            if item["kind"] == EntityKind.REQUIREMENT.value
        ]
        proposal = {
            "entities": [],
            "relations": [],
            "updates": [],
            "deprecations": [],
            "reason": "逐条需求生成功能模型",
            "assumptions": [],
            "open_questions": [],
            "decision_records": [{
                "step": "functional_requirement",
                "decision": "每条 Requirement 生成独立功能并保留 canonical 追溯",
                "basis": [item["id"] for item in requirements],
            }],
        }
        for index, requirement in enumerate(requirements, start=1):
            function_ref = f"function-{index}"
            flow_ref = f"flow-{index}"
            scenario_ref = f"fscenario-{index}"
            name = f"实现：{requirement['name']}"
            proposal["entities"].extend((
                {
                    "local_ref": function_ref,
                    "kind": EntityKind.FUNCTION.value,
                    "name": name,
                    "payload": {
                        "behavior": f"实现{requirement['name']}",
                        "inputs": ["需求输入"],
                        "outputs": ["可追踪结果"],
                        "decomposition": ["解析需求", "执行功能", "反馈结果"],
                    },
                    "confidence": 0.95,
                    "source_ids": [],
                    "evidence_ids": [],
                    "lifecycle_ids": [],
                },
                {
                    "local_ref": flow_ref,
                    "kind": EntityKind.FUNCTIONAL_FLOW.value,
                    "name": f"结果流：{requirement['name']}",
                    "payload": {
                        "source_function_ids": [function_ref],
                        "target_function_ids": [function_ref],
                        "content": "需求输入和执行结果",
                    },
                    "confidence": 0.95,
                    "source_ids": [],
                    "evidence_ids": [],
                    "lifecycle_ids": [],
                },
                {
                    "local_ref": scenario_ref,
                    "kind": EntityKind.FUNCTIONAL_SCENARIO.value,
                    "name": f"场景：{requirement['name']}",
                    "payload": {
                        "function_ids": [function_ref],
                        "steps": ["接收需求", "执行功能", "返回结果"],
                    },
                    "confidence": 0.95,
                    "source_ids": [],
                    "evidence_ids": [],
                    "lifecycle_ids": [],
                },
            ))
            proposal["relations"].extend((
                {
                    "source_ref": requirement["id"],
                    "predicate": RelationPredicate.SATISFIED_BY.value,
                    "target_ref": function_ref,
                    "evidence_ids": [],
                },
                {
                    "source_ref": function_ref,
                    "predicate": RelationPredicate.EXCHANGES_WITH.value,
                    "target_ref": flow_ref,
                    "evidence_ids": [],
                },
            ))
            proposal["updates"].append({
                "entity_id": requirement["id"],
                "field_patch": {"payload": {
                    "functional_behavior_ids": [function_ref],
                    "functional_requirement_status": "allocated",
                }},
            })
        return proposal


class FiveRequirementBatchedStructuredModel(ThreeRequirementStructuredModel):
    """Structured model double that consumes only the current V&V batch."""

    supports_requirement_batching = True

    def complete_json(self, request):
        if request.lens_id != "vertical.verification_validation":
            return super().complete_json(request)
        self.requirement_worklists.append(
            request.user_payload.get("requirement_worklist", [])
        )
        batch_ids = {
            item["requirement_id"]
            for item in request.user_payload["requirement_worklist"]
        }
        context = request.user_payload["context"]
        filtered_context = {
            **context,
            "entities": [
                item
                for item in context["entities"]
                if item["kind"] != EntityKind.REQUIREMENT.value
                or item["id"] in batch_ids
            ],
        }
        filtered_request = replace(
            request,
            user_payload={**request.user_payload, "context": filtered_context},
        )
        recorded = ScriptedModel.complete_json(self, filtered_request)
        return replace(
            recorded,
            payload=self._assurance_proposal(filtered_request),
        )


class FiveRequirementBatchFailureModel(FiveRequirementBatchedStructuredModel):
    def complete_json(self, request):
        if (
            request.lens_id == "vertical.verification_validation"
            and request.user_payload["requirement_batch"]["index"] == 2
        ):
            raise TransportFailure(
                "V&V batch provider unavailable",
                code="network_error",
                provider_id="fake",
                model_id="scripted",
            )
        return super().complete_json(request)


def test_structured_runtime_generates_three_requirement_vertical_model(tmp_path: Path):
    model = ThreeRequirementStructuredModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot",
        requirement_text="系统应自主配送；系统应支持人工接管；系统应在断网后安全运行",
    )
    graph = services.model("robot").graph("robot")

    requirements = sorted(
        (
            item for item in graph.entities
            if item.kind is EntityKind.REQUIREMENT
        ),
        key=lambda item: item.id,
    )
    assert result.status == "completed"
    assert all(stage.status == "completed" for stage in result.stage_results)
    assert all(stage.completion_issue_codes == () for stage in result.stage_results)
    assert all(stage.attempts == 1 for stage in result.stage_results)
    assert result.traceability.end_to_end_complete_count == 3
    assert len(tuple(
        item for item in graph.entities if item.kind is EntityKind.FUNCTION
    )) == 3
    assert all(resolve_requirement_trace(graph, item.id).complete for item in requirements)
    assert all(
        [item["requirement_id"] for item in worklist]
        == [item.id for item in requirements]
        for worklist in model.requirement_worklists
    )

    exported = graph_to_sysml(graph)
    restored = sysml_to_graph(exported, "robot")
    assert [item.as_dict() for item in restored.entities] == [
        item.as_dict() for item in graph.entities
    ]
    assert restored.relations == graph.relations

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.model("robot").apply_patch(
        "robot",
        Patch.create(
            "robot",
            "review.edit",
            (UpdateEntity(function.id, {"payload": {"review_note": "可继续编辑"}}),),
            "编辑多需求结构化模型",
            graph.revision,
        ),
        graph.revision,
    )
    edited = services.model("robot").graph("robot")
    assert edited.revision == graph.revision + 1
    assert edited.entity_index[function.id].payload["review_note"] == "可继续编辑"


def test_structured_runtime_batches_five_requirement_vv_and_keeps_full_trace(tmp_path: Path):
    model = FiveRequirementBatchedStructuredModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("drone")

    result = services.generation("drone").generate(
        "drone",
        requirement_text=(
            "系统应按航线巡检；系统应采集图像；系统应上传巡检结果；"
            "系统应在通信中断后进入安全模式；系统应在低电量时安全返航"
        ),
    )
    graph = services.model("drone").graph("drone")

    requirements = sorted(
        (
            item for item in graph.entities
            if item.kind is EntityKind.REQUIREMENT
        ),
        key=lambda item: item.id,
    )
    assert result.status == "completed"
    assert all(stage.status == "completed" for stage in result.stage_results)
    assert result.traceability.end_to_end_complete_count == 5
    assert len(tuple(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )) == 5
    assert len(tuple(
        item for item in graph.entities
        if item.kind is EntityKind.VALIDATION_CASE
    )) == 5
    assert all(resolve_requirement_trace(graph, item.id).complete for item in requirements)
    vv_batches = [
        worklist
        for lens_id, worklist in zip(model.calls, model.requirement_worklists)
        if lens_id == "vertical.verification_validation"
    ]
    assert [len(worklist) for worklist in vv_batches] == [2, 2, 1]
    vv_stage = next(
        stage
        for stage in result.stage_results
        if stage.stage == "verification_validation"
    )
    assert "batch_count=3" in vv_stage.diagnostics

    exported = graph_to_sysml(graph)
    restored = sysml_to_graph(exported, "drone")
    assert [item.as_dict() for item in restored.entities] == [
        item.as_dict() for item in graph.entities
    ]
    assert restored.relations == graph.relations

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.model("drone").apply_patch(
        "drone",
        Patch.create(
            "drone",
            "review.edit",
            (UpdateEntity(function.id, {"payload": {"review_note": "可继续编辑"}}),),
            "编辑批量 V&V 模型",
            graph.revision,
        ),
        graph.revision,
    )
    assert services.model("drone").graph("drone").revision == graph.revision + 1


def test_structured_runtime_vv_batch_failure_does_not_commit_partial_model(tmp_path: Path):
    model = FiveRequirementBatchFailureModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("drone")

    result = services.generation("drone").generate(
        "drone",
        requirement_text=(
            "系统应按航线巡检；系统应采集图像；系统应上传巡检结果；"
            "系统应在通信中断后进入安全模式；系统应在低电量时安全返航"
        ),
    )
    graph = services.model("drone").graph("drone")

    assert result.status == "failed"
    assert [stage.stage for stage in result.stage_results] == [
        "requirements",
        "functional",
        "logical",
        "physical",
    ]
    assert graph.revision == result.stage_results[-1].revision
    assert not any(
        entity.kind in {
            EntityKind.VERIFICATION_CASE,
            EntityKind.VALIDATION_CASE,
        }
        for entity in graph.entities
    )


def test_structured_runtime_generates_complete_editable_vertical_model(tmp_path: Path):
    model = CompleteVerticalModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot",
        requirement_text="系统应在校园内完成配送并支持人工接管",
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert all(stage.status == "completed" for stage in result.stage_results)
    assert all(stage.completion_issue_codes == () for stage in result.stage_results)
    assert all(stage.attempts == 1 for stage in result.stage_results)
    assert result.traceability.end_to_end_complete_count == 1
    assert model.calls == [
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ]
    assert {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.LIFECYCLE_TRANSITION,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.REQUIREMENT,
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.INTERFACE,
        EntityKind.STATE,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
        EntityKind.HAZARD,
        EntityKind.FAILURE_MODE,
    } <= {item.kind for item in graph.entities}

    graph_ids = {item.id for item in graph.entities}
    graph_reference_fields = {
        "activity_ids", "actor_ids", "connected_component_ids", "dependencies",
        "dependency_ids", "depends_on", "depends_on_ids", "functional_behavior_ids",
        "functional_flow_ids", "function_ids", "impact_entity_ids",
        "internal_component_ids", "logical_component_ids", "logical_id", "logical_ids",
        "owner_id", "physical_candidate_ids", "physical_ids", "requirement_ids",
        "scenario_ids", "shared_state_ids", "source_context_ids", "source_function_ids",
        "source_logical_ids", "source_physical_ids", "source_requirement_ids",
        "stakeholder_ids", "target_function_ids",
    }

    def assert_graph_references(value, field=""):
        if isinstance(value, dict):
            for key, item in value.items():
                assert_graph_references(item, str(key))
        elif field in graph_reference_fields:
            references = value if isinstance(value, list) else [value]
            assert set(references) <= graph_ids
        elif isinstance(value, list):
            for item in value:
                assert_graph_references(item, field)

    for entity in graph.entities:
        assert_graph_references(entity.payload)
    activity = next(item for item in graph.entities if item.kind is EntityKind.ACTIVITY)
    verification = next(
        item for item in graph.entities if item.kind is EntityKind.VERIFICATION_CASE
    )
    assert verification.payload["activity_ids"] == [activity.id]
    assert verification.payload["covered_branches"] == ["人工接管"]

    exported = graph_to_sysml(graph)
    restored = sysml_to_graph(exported, "robot")
    assert [item.as_dict() for item in restored.entities] == [
        item.as_dict() for item in graph.entities
    ]
    assert restored.relations == graph.relations

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.model("robot").apply_patch(
        "robot",
        Patch.create(
            "robot",
            "review.edit",
            (UpdateEntity(function.id, {"payload": {"review_note": "人工可继续编辑"}}),),
            "继续编辑结构化模型",
            graph.revision,
        ),
        graph.revision,
    )
    edited = services.model("robot").graph("robot")
    assert edited.revision == graph.revision + 1
    assert edited.entity_index[function.id].payload["review_note"] == "人工可继续编辑"


def test_vertical_assurance_emits_five_structured_branch_scenarios(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
    )
    services.projects.create("branch-model")
    result = services.generation("branch-model").generate(
        "branch-model",
        requirement_text="系统应支持人工接管",
    )
    graph = services.model("branch-model").graph("branch-model")
    cases = [
        entity for entity in graph.entities
        if entity.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
    ]

    assert result.status == "completed"
    assert len(cases) == 2
    expected = {"normal", "failure", "alternative", "boundary", "exception"}
    for case in cases:
        scenarios = case.payload["branch_scenarios"]
        assert {item["branch_type"] for item in scenarios} == expected
        assert all(
            item["activity_id"]
            and item["requirement_ids"]
            and item["stimulus"]
            and item["procedure"]
            and item["expected_result"]
            and item["pass_criteria"]
            for item in scenarios
        )
        assert all(item["status"] == "planned" for item in scenarios)

def test_intake_aware_structured_provider_generates_complete_document_model(tmp_path: Path):
    model = IntakeAwareCompleteVerticalModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot", "校园配送机器人")
    document = services.projects.ingest_uploaded(
        "robot",
        "requirements.txt",
        "系统应完成校园配送。".encode("utf-8"),
    )

    result = services.generation("robot").generate(
        "robot",
        document_ids=(document["document_id"],),
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert result.traceability.end_to_end_complete_count == 1
    assert model.calls[0] == "requirements.use_case"
    assert {
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    } <= set(model.calls[1:])
    intake_request = model.intake_requests[0]
    assert intake_request.response_schema["$id"] == "requirements-use-case-draft.v1"
    assert intake_request.user_payload["source_refs"] == (model.intake_source_ref,)
    assert intake_request.user_payload["source_regions"][0]["id"] == model.intake_source_ref
    assert any(
        event["kind"] == "model_generation.input_intake"
        and event["payload"].get("mode") == "structured_intake"
        for event in services.repository("robot").list_audit_events("robot")
    )

    required_kinds = {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.REQUIREMENT,
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    }
    assert required_kinds <= {item.kind for item in graph.entities}
    requirement = next(
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.meta.name == "系统应完成校园配送"
    )
    assert model.intake_source_ref in requirement.meta.source_ids
    assert model.intake_source_ref in requirement.meta.evidence_ids
    assert resolve_requirement_trace(graph, requirement.id).complete

    exported = graph_to_sysml(graph)
    restored = sysml_to_graph(exported, "robot")
    assert restored.entities == graph.entities
    assert restored.relations == graph.relations
    package = services.deliverables("robot").build("robot")
    assert package["manifest"]["revision"] == graph.revision
    assert package["manifest"]["snapshot_hash"] == graph.snapshot_hash
    assert package["artifacts"]["behavior"]["content"]["use_cases"]
    assert package["artifacts"]["sysml"]["content"] == exported


def test_complete_structured_model_supports_controller_physical_trade_study(tmp_path: Path):
    model = CompleteVerticalModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")
    generation = services.generation("robot")
    generated = generation.generate(
        "robot",
        requirement_text="系统应在校园内完成配送并支持人工接管",
    )
    graph = services.model("robot").graph("robot")
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    interface = next(item for item in graph.entities if item.kind is EntityKind.INTERFACE)

    accepted = services.review("robot").accept_entity(
        "robot", interface.id, expected_revision=graph.revision
    )
    services.review("robot").lock_entity(
        "robot", interface.id, expected_revision=accepted.revision["sequence"]
    )
    graph = services.model("robot").graph("robot")
    locked_snapshot = graph.entity_index[interface.id].as_dict()
    edited_requirement = services.review("robot").edit_entity(
        "robot",
        requirement.id,
        payload={**requirement.payload, "constraints": {"max_power_w": 50}},
        expected_revision=graph.revision,
    )
    graph = services.model("robot").graph("robot")
    services.review("robot").edit_entity(
        "robot",
        physical.id,
        payload={**physical.payload, "power_w": 80},
        expected_revision=edited_requirement.revision["sequence"],
    )
    before = services.model("robot").graph("robot")

    plan = generation.controller_plan("robot")
    action = plan["next_action"]
    assert "physical_constraint_conflict" in plan["findings"]
    assert action["kind"] == "trade_study"
    option = next(
        item for item in action["options"]
        if item["task_id"] == "allocation_tradeoff"
    )

    waiting = generation.iterate_controller(
        "robot", expected_revision=before.revision, max_iterations=3
    )
    assert waiting["execution_status"] == "awaiting_decision"
    assert waiting["revision"] == before.revision
    assert waiting["iterations"] == []

    selected = generation.execute_controller_action(
        "robot",
        action_id=action["id"],
        option_id=option["id"],
        expected_revision=before.revision,
    )
    after = services.model("robot").graph("robot")

    assert selected["execution_status"] == "completed"
    assert selected["reanalysis"]["selected_stages"] == [
        "physical", "verification_validation"
    ]
    assert selected["reanalysis"]["before_traceability"]
    assert selected["reanalysis"]["after_traceability"]
    alternative = next(
        item for item in after.entities
        if item.kind is EntityKind.PHYSICAL_BLOCK
        and item.payload.get("candidate_variant") == "alternative"
    )
    assert alternative.payload["power_w"] == 40.0
    assert alternative.payload["architecture_decision"]["option_id"] == option["id"]
    assert after.entity_index[interface.id].as_dict() == locked_snapshot
    assert after.entity_index[physical.id].payload["power_w"] == 80


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
            if request.user_payload["context"]["revision"] > 1:
                response.payload["entities"] = []
                response.payload["relations"] = []
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
            {
                "method": "test",
                "verification_objective": "证明需求在规定条件下满足",
                "precondition": "设备上电",
                "test_condition": "标准运行环境和需求边界条件",
                "input": "配送任务",
                "stimulus": "提交配送任务",
                "procedure": "执行任务并采集结果",
                "expected_result": "任务完成",
                "pass_criteria": "满足需求",
                "requirement_ids": [requirement.id],
                "function_ids": [function.id],
                "logical_component_ids": [logical.id],
                "physical_ids": [physical.id],
            },
            status=EntityStatus.VALIDATED,
        )
        entities.append(case)
        relations.append(Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, case.id))
    if validation:
        case = make_entity(
            EntityKind.VALIDATION_CASE,
            "确认体验",
            {
                "method": "demonstration",
                "verification_objective": "确认用户场景目标达成",
                "precondition": "用户在场",
                "test_condition": "典型用户和代表性任务条件",
                "input": "配送任务",
                "stimulus": "用户执行配送操作",
                "procedure": "用户观察执行",
                "expected_result": "用户认可结果",
                "pass_criteria": "用户认可",
                "requirement_ids": [requirement.id],
                "function_ids": [function.id],
                "logical_component_ids": [logical.id],
                "physical_ids": [physical.id],
            },
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
    assert all(
        not stage.completion_issue_codes
        and all(check["passed"] for check in stage.completion_checks)
        for stage in result.stage_results
    )
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


def test_natural_language_generation_stores_constraint_provenance(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    services.generation("robot").generate(
        "robot", requirement_text="系统功耗不超过 50 W 且续航不少于 10 h"
    )
    requirement = next(
        item
        for item in services.model("robot").graph("robot").entities
        if item.kind is EntityKind.REQUIREMENT
    )

    assert requirement.payload["constraints"] == {
        "max_power_w": 50.0,
        "min_endurance_h": 10.0,
    }
    assert len(requirement.payload["constraint_provenance"]) == 2


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
    assert all(step.attempt == 1 for step in run.steps)


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

    assert result.status == "completed_with_warnings"
    assert model.calls == [
        "vertical.requirements",
        "vertical.requirements",
        "vertical.functional",
        "vertical.functional",
        "vertical.logical",
        "vertical.logical",
        "vertical.physical",
        "vertical.physical",
        "vertical.verification_validation",
        "vertical.verification_validation",
    ]
    assert all(stage.attempts >= 1 for stage in result.stage_results)
    assert all(stage.attempts == 2 for stage in result.stage_results)
    assert all(
        item["attempts"] == stage.attempts
        for item, stage in zip(result.as_dict()["stage_results"], result.stage_results)
    )
    assert result.traceability.complete_count == 1
    functional_stage = result.stage_results[1]
    assert functional_stage.status == "needs_review"
    assert "completion_semantic:functional_requirement" in functional_stage.completion_issue_codes
    assert any(
        check["id"] == "functional_requirement" and not check["passed"]
        for check in functional_stage.completion_checks
    )
    assert result.stage_results[2].decision_records[0]["step"] == "vertical.logical"
    functional_guidance = next(
        item for item in model.methodology_guidances
        if item["task_id"] == "vertical.functional"
    )
    logical_guidance = next(
        item for item in model.methodology_guidances
        if item["task_id"] == "vertical.logical"
    )
    assert functional_guidance["stage_completion"]["issue_codes"]
    assert any(
        check["id"] == "functional_requirement" and not check["passed"]
        for check in functional_guidance["stage_completion"]["checks"]
    )
    assert [item["task_id"] for item in model.methodology_guidances] == [
        "vertical.requirements",
        "vertical.requirements",
        "vertical.functional",
        "vertical.functional",
        "vertical.logical",
        "vertical.logical",
        "vertical.physical",
        "vertical.physical",
        "vertical.verification_validation",
        "vertical.verification_validation",
    ]
    assert logical_guidance["architecture_synthesis"]["logical"]
    assert "functional_requirement_coverage" in functional_guidance["metrics"]
    relation_context = [
        model_relation
        for context in model.relation_contexts
        for model_relation in context
    ]
    assert any(model_relation["predicate"] == "satisfiedBy" for model_relation in relation_context)
    assert set(relation_context[0]) == {"source_id", "predicate", "target_id"}


def test_structured_vertical_path_persists_missing_architecture_reasoning(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(ScriptedModel()),
    )
    services.projects.create("robot")

    services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    logical = next(
        item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT
    )
    physical = next(
        item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK
    )

    assert logical.payload["architecture_reasoning"]["basis"]["function_ids"]
    assert logical.payload["architecture_reasoning"]["alternatives"]
    assert physical.payload["feasibility_reasoning"]["physical_id"] == physical.id
    assert physical.payload["feasibility_reasoning"]["status"] == "needs_measurement"


def test_structured_runtime_retries_one_stage_with_latest_graph_and_guidance(tmp_path: Path):
    model = FeedbackFunctionalModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.stage_results[1].status == "completed"
    assert result.stage_results[1].attempts == 2
    assert result.stage_results[1].completion_issue_codes == ()
    assert model.functional_context_revisions == [2, 3]
    assert model.calls == [
        "vertical.requirements",
        "vertical.requirements",
        "vertical.functional",
        "vertical.functional",
        "vertical.logical",
        "vertical.logical",
        "vertical.physical",
        "vertical.physical",
        "vertical.verification_validation",
        "vertical.verification_validation",
    ]
    graph = services.model("robot").graph("robot")
    assert len(tuple(item for item in graph.entities if item.kind is EntityKind.FUNCTION)) == 1
    run = services.repository("robot").load_run("robot", result.run_id)
    functional_step = next(
        step for step in run.steps if step.task_id == "vertical.functional"
    )
    assert functional_step.attempt == 2
    stage_events = [
        event["payload"]
        for event in services.repository("robot").list_audit_events("robot")
        if event["kind"] == "model_generation.stage_completed"
        and event["payload"]["stage"] == "functional"
    ]
    assert stage_events[-1]["attempts"] == 2
    assert any(
        event["kind"] == "model_generation.stage_feedback"
        and event["payload"]["stage"] == "functional"
        and event["payload"]["next_attempt"] == 2
        for event in services.repository("robot").list_audit_events("robot")
    )


def test_multi_requirement_feedback_repairs_the_exact_missing_requirement(tmp_path: Path):
    model = TwoRequirementFeedbackModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")
    requirement_ids = services.requirements_input("robot").ensure_text_requirements(
        "系统应自主配送；系统应支持人工接管"
    )

    result = services.generation("robot").generate("robot")

    assert model.functional_attempts == 2
    assert result.stage_results[1].status == "completed"
    assert result.stage_results[1].attempts == 2
    first_gap = model.functional_guidances[0]["requirement_coverage"]
    second_gap = model.functional_guidances[1]["requirement_coverage"]
    assert set(first_gap["missing_requirement_ids"]) == set(requirement_ids)
    assert len(second_gap["missing_requirement_ids"]) == 1
    assert set(second_gap["missing_requirement_ids"]) < set(first_gap["missing_requirement_ids"])
    assert result.traceability.end_to_end_complete_count == 2


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


def test_controller_logical_trade_study_generates_versioned_architecture_variant(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")
    generated = generation.generate(
        "robot", requirement_text="系统应自主配送；系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    functions = [item for item in graph.entities if item.kind is EntityKind.FUNCTION]
    logicals = [
        item for item in graph.entities
        if item.kind is EntityKind.LOGICAL_COMPONENT
    ]
    assert len(functions) == len(logicals) == 2

    revision = graph.revision
    for function in functions:
        result = services.review("robot").edit_entity(
            "robot",
            function.id,
            payload={**function.payload, "shared_state": ["task_state"]},
            expected_revision=revision,
        )
        revision = result.revision["sequence"]
        result = services.review("robot").accept_entity(
            "robot", function.id, expected_revision=revision
        )
        revision = result.revision["sequence"]
    graph = services.model("robot").graph("robot")
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)
    services.model("robot").apply_patch(
        "robot",
        Patch.create(
            "robot",
            "architecture-review",
            (UpdateEntity(logical.id, {"payload": {**logical.payload, "coupling": "high"}}),),
            "制造待评审的逻辑耦合决策场景",
            graph.revision,
        ),
        graph.revision,
    )
    before = services.model("robot").graph("robot")
    report = generation.methodology_engine.analyze(before)
    plan = generation.controller.plan(before, report)
    action = next(
        item for item in plan.actions
        if item.kind == "trade_study" and item.stage == "logical"
    )
    option = next(
        item for item in action.options
        if item["option"] == "one_component_per_function"
    )

    result = generation.execute_controller_action(
        "robot",
        action_id=action.id,
        option_id=option["id"],
        expected_revision=before.revision,
    )
    after = services.model("robot").graph("robot")
    active_variants = [
        item for item in after.entities
        if item.kind is EntityKind.LOGICAL_COMPONENT
        and item.meta.status is not EntityStatus.DEPRECATED
        and item.payload.get("architecture_variant") == "one_component_per_function"
    ]

    assert after.revision > before.revision
    assert any(
        item.kind is EntityKind.LOGICAL_COMPONENT
        and item.meta.status is EntityStatus.DEPRECATED
        for item in after.entities
    )
    assert len(active_variants) == 2
    assert result["reanalysis"]["controller_decision"]["option_id"] == option["id"]
    assert result["reanalysis"]["traceability"]["complete_count"] > 0


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

    assert result.status == "completed_with_warnings"
    assert any(
        evidence["source_type"] == "document_region"
        and evidence["excerpt"] == "系统应支持人工接管"
        for context in model.evidence_contexts
        for evidence in context
    )


def test_vertical_generation_bounds_stage_context_to_configured_window(tmp_path: Path):
    model = ScriptedModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
        runtime_config={
            "id": "remote-test",
            "provider": "openai-compatible",
            "kind": "remote",
            "base_url": "https://example.invalid/v1",
            "model": "engineering-model",
            "context_window": 4096,
            "max_output_tokens": 1024,
        },
    )
    services.projects.create("robot")

    services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert model.calls == [
        "vertical.requirements",
        "vertical.requirements",
        "vertical.functional",
        "vertical.functional",
        "vertical.logical",
        "vertical.logical",
        "vertical.physical",
        "vertical.physical",
        "vertical.verification_validation",
        "vertical.verification_validation",
    ]
    assert all(
        estimate <= 2816
        for estimate in model.context_token_estimates
    )
    assurance_guidances = [
        guidance
        for lens_id, guidance in zip(model.calls, model.methodology_guidances)
        if lens_id == "vertical.verification_validation"
    ]
    assert assurance_guidances
    assert all("context_selection" in guidance for guidance in assurance_guidances)


def test_configured_vertical_generation_bridges_remaining_completion_gaps(tmp_path: Path):
    model = ScriptedModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
        runtime_config={
            "id": "configured-test",
            "provider": "openai-compatible",
            "kind": "remote",
            "base_url": "https://example.invalid/v1",
            "model": "engineering-model",
            "vertical_completion_bridge": True,
            "context_window": 8192,
            "max_output_tokens": 2048,
        },
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.traceability.complete_count == 1
    assert all(item.status == "completed" for item in result.stage_results)
    assert all(item.attempts == 2 for item in result.stage_results)
    assert all(
        "completion_bridge=vertical-rule" in item.diagnostics
        for item in result.stage_results
    )
    assert sum(
        event["kind"] == "model_generation.completion_bridge"
        for event in services.repository("robot").list_audit_events("robot")
    ) == 5


def test_configured_vertical_generation_can_skip_remote_feedback_and_still_bridge(tmp_path: Path):
    model = ScriptedModel()
    model.automatic_vertical_stage_feedback = False
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
        runtime_config={
            "id": "remote-fast-path",
            "provider": "openai-compatible",
            "kind": "local",
            "model_location": "remote",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "vertical_feedback": False,
            "vertical_completion_bridge": True,
            "context_window": 8192,
            "max_output_tokens": 2048,
        },
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.traceability.complete_count == 1
    assert all(item.status == "completed" for item in result.stage_results)
    assert all(item.attempts == 1 for item in result.stage_results)
    assert all(
        "completion_bridge=vertical-rule" in item.diagnostics
        for item in result.stage_results
    )
    assert model.calls == [
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ]


def test_configured_vertical_generation_bridges_transport_gap_after_rflp(tmp_path: Path):
    runtime = TransportFailingVerticalRuntime()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=runtime,
        runtime_config={
            "id": "remote-transport-gap",
            "provider": "openai-compatible",
            "kind": "remote",
            "base_url": "https://example.invalid/v1",
            "model": "engineering-model",
            "vertical_completion_bridge": True,
            "context_window": 8192,
            "max_output_tokens": 2048,
        },
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.status == "completed_with_warnings"
    assert result.traceability.complete_count == 1
    assert result.stage_results[-1].status == "needs_review"
    assert "llm_execution_unavailable" in result.stage_results[-1].completion_issue_codes
    assert "LLM execution unavailable" in result.warnings[-1]
    assert "completion_bridge=vertical-rule" in result.stage_results[-1].diagnostics


def test_completion_bridge_repairs_missing_requirement_semantics(tmp_path: Path):
    model = MissingRequirementObligationModel()
    model.automatic_vertical_stage_feedback = False
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
        runtime_config={
            "id": "remote-semantic-bridge",
            "provider": "openai-compatible",
            "kind": "local",
            "model_location": "remote",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "vertical_feedback": False,
            "vertical_completion_bridge": True,
            "context_window": 8192,
            "max_output_tokens": 2048,
        },
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    requirement = next(
        item
        for item in services.model("robot").graph("robot").entities
        if item.kind is EntityKind.REQUIREMENT
    )
    assert result.traceability.complete_count == 1
    assert result.stage_results[0].status == "completed"
    assert requirement.payload["obligation"] == "系统应"
    assert "completion_bridge=vertical-rule" in result.stage_results[0].diagnostics


def test_generation_attaches_read_only_controller_proposal(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    model = ControllerProposalModel()
    repository = services.repository("robot")
    generation = ModelGenerationService(
        repository,
        VerticalRuleRuntime(),
        llm_controller=LLMController(model),
    )

    generated = generation.generate("robot", requirement_text="系统应支持人工接管")
    revision_before_query = repository.load_graph("robot").revision
    plan = generation.controller_plan("robot")

    assert generated.controller.proposal.status == "proposed"
    assert plan["llm_proposal"]["status"] == "proposed"
    assert repository.load_graph("robot").revision == revision_before_query
    assert model.calls == 2

    deterministic_plan = generation.controller_plan("robot", include_llm=False)

    assert deterministic_plan["llm_proposal"] is None
    assert deterministic_plan["next_action"]["id"] == plan["next_action"]["id"]
    assert model.calls == 2


def test_controller_proposal_failure_does_not_fail_generation(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    model = ControllerProposalModel(
        TransportFailure(
            "remote unavailable",
            code="network_error",
            provider_id="remote",
            model_id="model",
        )
    )
    generation = ModelGenerationService(
        services.repository("robot"),
        VerticalRuleRuntime(),
        llm_controller=LLMController(model),
    )

    result = generation.generate("robot", requirement_text="系统应支持人工接管")

    assert result.status in {"completed", "completed_with_warnings"}
    assert result.controller.proposal.status == "fallback"
    assert result.controller.proposal.diagnostics == (
        "controller_proposal_network_error",
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
        runtime_config={"id": "configured-test", "model": "test-model"},
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


def test_feedback_transport_failure_keeps_applied_stage_for_downstream_work(
    tmp_path: Path, monkeypatch
):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(ScriptedModel()),
    )
    services.projects.create("robot")
    generation = services.generation("robot")
    run_id = generation.prepare_generation(
        "robot", requirement_text="系统应支持人工接管"
    )
    repository = services.repository("robot")
    graph = repository.load_graph("robot")
    stage = stage_spec("functional")
    task = stage_task("functional")
    function = make_entity(
        EntityKind.FUNCTION,
        "执行人工接管",
        {"decomposition": ["接收接管指令", "执行接管", "反馈状态"]},
        status=EntityStatus.VALIDATED,
        producer=Producer.LLM,
    )
    patch = Patch.create(
        "robot",
        task.id,
        (AddEntity(function),),
        "首次功能分析",
        graph.revision,
    )
    revision = repository.append_patch("robot", patch, graph.revision, run_id=run_id).sequence
    response = TaskExecutionResponse(
        StepStatus.COMPLETED,
        patch=patch,
        diagnostics=("provider=remote",),
        input_hash="input",
        output_hash="output",
        provider_id="remote",
        model_id="remote-model",
    )
    first = _StageAttemptResult(
        StageResult(
            "functional",
            "needs_review",
            revision,
            1,
            len(graph.relations),
            completion_issue_codes=("completion_requirement_coverage:functional",),
        ),
        warnings=("functional: incomplete",),
        response=response,
        context_hash="context-1",
        started_at=1.0,
    )
    calls = []

    def fail_feedback(*_args, **_kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return first
        return _StageAttemptResult(
            None,
            diagnostics=("remote feedback connection reset",),
            response=TaskExecutionResponse(
                StepStatus.DEGRADED,
                diagnostics=("remote feedback connection reset",),
            ),
        )

    monkeypatch.setattr(generation, "_execute_stage_attempt", fail_feedback)

    execution = generation._execute_stage(
        "robot", run_id, stage, graph, ()
    )

    assert calls == [1, 2]
    assert execution.result is not None
    assert execution.result.status == "needs_review"
    assert execution.result.revision == revision
    assert any("continuing with the previously committed partial result" in item for item in execution.warnings)
    run = repository.load_run("robot", run_id)
    functional_step = next(step for step in run.steps if step.task_id == task.id)
    assert functional_step.status == StepStatus.COMPLETED.value
    assert any(
        event["kind"] == "model_generation.stage_feedback_failed"
        for event in repository.list_audit_events("robot")
    )


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


def test_traceability_summary_closes_technical_requirement_from_root_to_physical():
    graph = _trace_graph(verification=True, validation=True)
    root = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    technical = make_entity(
        EntityKind.REQUIREMENT,
        "计算单元功耗约束",
        {"level": "technical", "constraints": {"max_power_w": 50}},
        status=EntityStatus.VALIDATED,
    )
    assurance_scope = {
        "requirement_ids": [technical.id],
        "function_ids": [
            item.id for item in graph.entities if item.kind is EntityKind.FUNCTION
        ],
        "logical_component_ids": [
            item.id for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT
        ],
        "physical_ids": [physical.id],
    }
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证计算单元功耗",
        assurance_scope,
        status=EntityStatus.VALIDATED,
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "确认计算单元功耗",
        assurance_scope,
        status=EntityStatus.VALIDATED,
    )
    graph = ModelGraph(
        graph.project_id,
        (*graph.entities, technical, verification, validation),
        (
            *graph.relations,
            Relation("technical-root", technical.id, RelationPredicate.DERIVED_FROM, root.id),
            Relation("technical-physical", technical.id, RelationPredicate.SATISFIED_BY, physical.id),
            Relation("technical-verification", technical.id, RelationPredicate.VERIFIED_BY, verification.id),
            Relation("technical-validation", technical.id, RelationPredicate.VALIDATED_BY, validation.id),
        ),
        revision=graph.revision,
    )

    summary = build_traceability_summary(graph)

    assert summary.end_to_end_complete_count == 2
    assert any(path[0] == technical.id and physical.id in path for path in summary.paths)


def test_traceability_summary_path_uses_the_canonical_projection_ids():
    graph = _trace_graph(verification=True, validation=True)
    requirement_id = next(
        item.id for item in graph.entities if item.kind is EntityKind.REQUIREMENT
    )

    summary = build_traceability_summary(graph)
    row = next(
        item for item in build_traceability_view(graph)["rows"]
        if item["requirement_id"] == requirement_id
    )

    assert tuple(summary.paths[0][:4]) == tuple([
        requirement_id,
        row["functions"][0],
        row["logical_components"][0],
        row["physical_blocks"][0],
    ])


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
    assert result["impact"]["revision"] == result["trigger_revision"]
    assert result["impact"]["trigger_entity_ids"] == [function.id]
    assert result["before_traceability"]["revision"] <= result["after_traceability"]["revision"]
    assert result["impacted_vv_case_ids"]
    assert len(result["stage_results"]) == 4


def test_requirement_reanalysis_updates_one_active_downstream_chain(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    services.generation("robot").generate(
        "robot", requirement_text="系统应自主完成配送"
    )
    graph = services.model("robot").graph("robot")
    requirement = next(
        item for item in graph.entities if item.kind is EntityKind.REQUIREMENT
    )
    original_ids = {
        kind: next(item.id for item in graph.entities if item.kind is kind)
        for kind in (
            EntityKind.FUNCTION,
            EntityKind.LOGICAL_COMPONENT,
            EntityKind.PHYSICAL_BLOCK,
            EntityKind.VERIFICATION_CASE,
            EntityKind.VALIDATION_CASE,
        )
    }
    edited = services.review("robot").edit_entity(
        "robot",
        requirement.id,
        statement="系统应支持人工接管",
        expected_revision=graph.revision,
    )

    result = services.generation("robot").reanalyze(
        "robot",
        requirement.id,
        expected_revision=edited.revision["sequence"],
    )

    current = services.model("robot").graph("robot")
    active = tuple(
        item for item in current.entities
        if item.meta.status is not EntityStatus.DEPRECATED
    )
    active_functions = tuple(item for item in active if item.kind is EntityKind.FUNCTION)
    active_logical = tuple(
        item for item in active if item.kind is EntityKind.LOGICAL_COMPONENT
    )
    active_physical = tuple(
        item for item in active if item.kind is EntityKind.PHYSICAL_BLOCK
    )
    active_verification = tuple(
        item for item in active if item.kind is EntityKind.VERIFICATION_CASE
    )
    active_validation = tuple(
        item for item in active if item.kind is EntityKind.VALIDATION_CASE
    )

    assert result["execution_status"] == "completed"
    assert len(active_functions) == 1
    assert active_functions[0].id == original_ids[EntityKind.FUNCTION]
    assert "人工接管" in active_functions[0].payload["behavior"]
    assert len(active_logical) == 1
    assert active_logical[0].id == original_ids[EntityKind.LOGICAL_COMPONENT]
    assert len(active_physical) == 1
    assert active_physical[0].id == original_ids[EntityKind.PHYSICAL_BLOCK]
    assert len(active_verification) == 1
    assert active_verification[0].id == original_ids[EntityKind.VERIFICATION_CASE]
    assert "人工接管" in active_verification[0].payload["input"]
    assert len(active_validation) == 1
    assert active_validation[0].id == original_ids[EntityKind.VALIDATION_CASE]
    assert "人工接管" in active_validation[0].payload["input"]
    assert any(
        item.kind is EntityKind.FUNCTION
        and item.meta.status is EntityStatus.DEPRECATED
        for item in current.entities
    ) is False
    assert result["traceability"]["complete_count"] >= 1


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
