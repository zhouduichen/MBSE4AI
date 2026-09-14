"""Deterministic offline runtime used when no model profile is configured."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
import re

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Deprecate, ModelGraph, Patch, Relate, UpdateEntity, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_reasoning import (
    logical_reasoning_payload,
    physical_reasoning_payload,
)
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.methodology.vertical_coverage import resolve_requirement_trace
from rflp_lite.runtime.lifecycle_rule import (
    LIFECYCLE_TASKS,
    LifecycleTaskRuleRuntime,
)


_PRIMARY_OUTPUT: dict[str, EntityKind] = {
    "system_definition": EntityKind.SYSTEM,
    "stakeholder_analysis": EntityKind.CONCERN,
    "stakeholder_requirements": EntityKind.REQUIREMENT,
    "lifecycle_analysis": EntityKind.LIFECYCLE_STAGE,
    "scenario_exploration": EntityKind.SCENARIO_HYPOTHESIS,
    "use_case_analysis": EntityKind.USE_CASE,
    "operational_scenario": EntityKind.OPERATIONAL_SCENARIO,
    "activity_analysis": EntityKind.ACTIVITY,
    "system_requirement_derivation": EntityKind.REQUIREMENT,
    "function_identification": EntityKind.FUNCTION,
    "functional_decomposition": EntityKind.FUNCTION,
    "functional_interaction": EntityKind.FUNCTIONAL_FLOW,
    "functional_scenario": EntityKind.FUNCTIONAL_SCENARIO,
    "functional_requirement": EntityKind.REQUIREMENT,
    "logical_analysis": EntityKind.LOGICAL_COMPONENT,
    "physical_candidates": EntityKind.PHYSICAL_BLOCK,
    "allocation_tradeoff": EntityKind.PHYSICAL_BLOCK,
    "technical_requirement": EntityKind.REQUIREMENT,
    "interface_sequence_state": EntityKind.INTERFACE,
    "fmea_stpa_hazard": EntityKind.HAZARD,
    "verification_validation": EntityKind.VERIFICATION_CASE,
    "reverse_feasibility": EntityKind.REQUIREMENT,
    "global_cross_analysis": EntityKind.VALIDATION_CASE,
}
_LOGICAL_VARIANTS = frozenset({
    "one_component_per_function", "shared_coordinator", "current_dependency_partition",
    "dependency_cluster_search",
})
_PHYSICAL_VARIANTS = frozenset({
    "更换物理候选或计算架构", "降低计算或功耗需求",
    "调整需求约束或资源预算", "增加电池质量或资源预算",
})
_LIFECYCLE_RUNTIME = LifecycleTaskRuleRuntime()


def _first(context, kind: EntityKind):
    return next((item for item in context.entities if item.kind is kind), None)


class RuleRuntime:
    """Create reviewable candidates from context without inventing source facts."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        if request.task_id.startswith("vertical."):
            return VerticalRuleRuntime().execute(request)
        if request.task_id in LIFECYCLE_TASKS:
            return _LIFECYCLE_RUNTIME.execute(request)
        if request.task_id == "verification_validation":
            return self._verification_validation(request)
        if request.task_id == "global_cross_analysis":
            response = self._cross_analysis_links(request)
            if response is not None:
                return response
        kind = _PRIMARY_OUTPUT.get(request.task_id)
        if kind is None or kind.value not in {str(value) for value in request.output_contract.get("output_kinds", ())}:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:no-op",))
        if request.task_id == "system_definition":
            existing = _first(request.context_bundle, EntityKind.SYSTEM)
            if existing is not None:
                payload = {
                    "mission": "待确认",
                    "system_boundary": {"inside": [], "outside": []},
                    "objectives": ["待确认"],
                    "environment_assumptions": ["待确认"],
                    "exclusions": ["待确认"],
                    "open_questions": ["待确认"],
                }
                patch = Patch.create(
                    request.context_bundle.project_id,
                    request.task_id,
                    (UpdateEntity(existing.id, {"payload": payload}),),
                    "离线规则补全系统定义",
                    request.context_bundle.revision,
                )
                return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch, diagnostics=("offline:system-update",))
        name = f"{request.task_id} 候选"
        existing = next((item for item in request.context_bundle.entities if item.kind is kind and item.meta.name == name), None)
        if existing is not None:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:idempotent",))
        payload: dict[str, object] = {"task_id": request.task_id, "requires_human_review": True}
        if kind is EntityKind.SYSTEM:
            payload = {
                "mission": "待确认",
                "system_boundary": {"inside": [], "outside": []},
                "objectives": ["待确认"],
                "environment_assumptions": ["待确认"],
                "exclusions": ["待确认"],
                "open_questions": ["待确认"],
            }
        if kind is EntityKind.REQUIREMENT:
            payload.update({"level": "system", "type": "functional", "obligation": "待确认", "verification_method": "review"})
        if kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}:
            is_verification = kind is EntityKind.VERIFICATION_CASE
            payload.update({
                "method": "review" if is_verification else "demonstration",
                "verification_objective": "待确认的需求验证或场景确认目标",
                "precondition": "待确认的系统和执行初始状态",
                "test_condition": "待确认的环境、配置、工况和边界条件",
                "input": "待确认的测试数据、对象或任务",
                "stimulus": "待确认的系统事件、操作或输入序列",
                "procedure": "待确认的可重复执行步骤",
                "expected_result": "待确认的可观察结果",
                "pass_criteria": "待确认的通过准则",
            })
        if kind is EntityKind.OPERATIONAL_SCENARIO:
            payload.update({"actor_ids": [item.id for item in request.context_bundle.entities if item.kind is EntityKind.STAKEHOLDER], "exchanges": [], "steps": [], "internal_component_ids": []})
        entity = make_entity(kind, name, payload, status=EntityStatus.CANDIDATE, producer=Producer.RULE, confidence=0.5, revision=request.context_bundle.revision)
        operations: list[object] = [AddEntity(entity)]
        context = request.context_bundle
        requirements = [item for item in context.entities if item.kind is EntityKind.REQUIREMENT]
        functions = [item for item in context.entities if item.kind is EntityKind.FUNCTION]
        logical = _first(context, EntityKind.LOGICAL_COMPONENT)
        if kind is EntityKind.FUNCTION:
            operations.extend(Relate(item.id, RelationPredicate.SATISFIED_BY, entity.id) for item in requirements)
        elif kind is EntityKind.LOGICAL_COMPONENT:
            operations.extend(Relate(item.id, RelationPredicate.ALLOCATED_TO, entity.id) for item in functions)
        elif kind is EntityKind.PHYSICAL_BLOCK and logical:
            operations.append(Relate(logical.id, RelationPredicate.ALLOCATED_TO, entity.id))
        elif kind is EntityKind.VERIFICATION_CASE:
            operations.extend(Relate(item.id, RelationPredicate.VERIFIED_BY, entity.id) for item in requirements)
        elif kind is EntityKind.INTERFACE:
            operations.extend(Relate(item.id, RelationPredicate.EXCHANGES_WITH, entity.id) for item in functions)
        elif kind is EntityKind.OPERATIONAL_SCENARIO:
            operations.extend(
                Relate(item.id, RelationPredicate.PARTICIPATES_IN, entity.id)
                for item in context.entities if item.kind is EntityKind.STAKEHOLDER
            )
        elif kind is EntityKind.REQUIREMENT:
            operations.extend(
                Relate(entity.id, RelationPredicate.SATISFIED_BY, item.id)
                for item in functions
            )
            operations.extend(
                Relate(entity.id, RelationPredicate.VERIFIED_BY, item.id)
                for item in context.entities if item.kind is EntityKind.VERIFICATION_CASE
            )
            operations.extend(
                Relate(entity.id, RelationPredicate.VALIDATED_BY, item.id)
                for item in context.entities if item.kind is EntityKind.VALIDATION_CASE
            )
        elif kind is EntityKind.VALIDATION_CASE:
            operations.extend(
                Relate(item.id, RelationPredicate.VALIDATED_BY, entity.id)
                for item in requirements
            )
        patch = Patch.create(context.project_id, request.task_id, tuple(operations), f"离线规则生成 {kind.value} 候选", context.revision)
        return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch, diagnostics=("offline:rule-runtime",))

    def _cross_analysis_links(self, request: TaskExecutionRequest) -> TaskExecutionResponse | None:
        context = request.context_bundle
        requirements = [item for item in context.entities if item.kind is EntityKind.REQUIREMENT]
        verifications = [item for item in context.entities if item.kind is EntityKind.VERIFICATION_CASE]
        validations = [item for item in context.entities if item.kind is EntityKind.VALIDATION_CASE]
        existing = {
            (item.source_id, item.predicate, item.target_id)
            for item in context.relations
        }
        operations: list[object] = []
        for requirement in requirements:
            for case in verifications:
                key = (requirement.id, RelationPredicate.VERIFIED_BY, case.id)
                if key not in existing:
                    operations.append(Relate(*key))
                    existing.add(key)
            for case in validations:
                key = (requirement.id, RelationPredicate.VALIDATED_BY, case.id)
                if key not in existing:
                    operations.append(Relate(*key))
                    existing.add(key)
        if operations:
            patch = Patch.create(
                context.project_id,
                request.task_id,
                tuple(operations),
                "离线规则补齐全局需求验证追踪",
                context.revision,
            )
            return TaskExecutionResponse(
                StepStatus.COMPLETED,
                patch=patch,
                diagnostics=("offline:cross-analysis-links",),
            )
        if validations:
            return TaskExecutionResponse(
                StepStatus.COMPLETED,
                diagnostics=("offline:assurance-already-covered",),
            )
        return None

    def _verification_validation(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        context = request.context_bundle
        requirements = [item for item in context.entities if item.kind is EntityKind.REQUIREMENT]
        existing = {(item.kind, item.meta.name): item for item in context.entities}
        operations: list[object] = []
        cases = {}
        for kind, name, predicate, method in (
            (EntityKind.VERIFICATION_CASE, "verification_validation 验证候选", RelationPredicate.VERIFIED_BY, "review"),
            (EntityKind.VALIDATION_CASE, "verification_validation 确认候选", RelationPredicate.VALIDATED_BY, "demonstration"),
        ):
            case = existing.get((kind, name))
            if case is None:
                case = make_entity(
                    kind,
                    name,
                    {
                        "task_id": request.task_id,
                        "method": method,
                        "verification_objective": "待确认的需求验证或场景确认目标",
                        "precondition": "待确认的系统和执行初始状态",
                        "test_condition": "待确认的环境、配置、工况和边界条件",
                        "input": "待确认的测试数据、对象或任务",
                        "stimulus": "待确认的系统事件、操作或输入序列",
                        "procedure": "待确认的可重复执行步骤",
                        "expected_result": "待确认的可观察结果",
                        "pass_criteria": "待确认的通过准则",
                        "requires_human_review": True,
                    },
                    status=EntityStatus.CANDIDATE,
                    producer=Producer.RULE,
                    confidence=0.5,
                    revision=context.revision,
                )
                operations.append(AddEntity(case))
            cases[kind] = (case, predicate)
        relation_keys = {(item.source_id, item.predicate, item.target_id) for item in context.relations}
        for requirement in requirements:
            for case, predicate in cases.values():
                key = (requirement.id, predicate, case.id)
                if key not in relation_keys:
                    operations.append(Relate(requirement.id, predicate, case.id))
                    relation_keys.add(key)
        if not operations:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:idempotent",))
        patch = Patch.create(context.project_id, request.task_id, tuple(operations), "离线规则生成验证与确认候选", context.revision)
        return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch, diagnostics=("offline:rule-runtime",))


class _VerticalPatchBuilder:
    def __init__(self, request: TaskExecutionRequest):
        self.request = request
        self.context = request.context_bundle
        self.index = {item.id: item for item in self.context.entities}
        self.operations: list[object] = []
        self.added: dict[str, object] = {}
        self.deprecated = set()
        self.relation_keys = {
            (item.source_id, item.predicate, item.target_id)
            for item in self.context.relations
        }

    def find(self, kind: EntityKind, name: str):
        return next(
            (
                item for item in tuple(self.index.values()) + tuple(self.added.values())
                if item.kind is kind and item.meta.name == name
            ),
            None,
        )

    def add(self, kind: EntityKind, name: str, payload: Mapping[str, object]):
        existing = self.find(kind, name)
        if existing is not None:
            return existing
        entity = make_entity(
            kind,
            name,
            payload,
            status=EntityStatus.VALIDATED,
            producer=Producer.RULE,
            confidence=0.8,
            revision=self.context.revision,
        )
        self.added[entity.id] = entity
        self.operations.append(AddEntity(entity))
        return entity

    def relate(self, source, predicate: RelationPredicate, target):
        if source is None or target is None:
            return
        key = (source.id, predicate, target.id)
        if key in self.relation_keys:
            return
        self.relation_keys.add(key)
        self.operations.append(Relate(source.id, predicate, target.id))

    def deprecate(self, entity) -> None:
        if entity.meta.status in {EntityStatus.DEPRECATED, EntityStatus.LOCKED}:
            return
        if bool(entity.payload.get("user_modified")) or entity.id in self.deprecated:
            return
        self.deprecated.add(entity.id)
        self.operations.append(Deprecate(entity.id))

    def update_payload(self, entity, payload: Mapping[str, object]) -> bool:
        return self.update(entity, payload=payload)

    def update(
        self,
        entity,
        *,
        name: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> bool:
        if entity.meta.status in {EntityStatus.DEPRECATED, EntityStatus.LOCKED}:
            return False
        if bool(entity.payload.get("user_modified")):
            return False
        fields = {}
        if name is not None and str(name).strip() and str(name).strip() != entity.meta.name:
            fields["name"] = str(name).strip()
        if payload is not None and dict(payload) != dict(entity.payload):
            fields["payload"] = dict(payload)
        if fields:
            self.operations.append(UpdateEntity(entity.id, fields))
        return True

    def response(self) -> TaskExecutionResponse:
        if not self.operations:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:vertical-idempotent",))
        patch = Patch.create(
            self.context.project_id,
            self.request.task_id,
            tuple(self.operations),
            f"离线纵向生成 {self.request.task_id}",
            self.context.revision,
        )
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            patch=patch,
            diagnostics=("offline:vertical-runtime",),
            decision_records=_vertical_decision_records(self.request.task_id, self.context, self.added),
        )


class VerticalRuleRuntime:
    """Concrete offline generator used to exercise the product path."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        handler = {
            "vertical.requirements": self._requirements,
            "vertical.functional": self._functional,
            "vertical.logical": self._logical,
            "vertical.physical": self._physical,
            "vertical.verification_validation": self._verification_validation,
        }.get(request.task_id)
        if handler is None:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:vertical-no-op",))
        return handler(request)

    def _requirements(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        requirements = _requirements(request)
        if not requirements:
            subject, source = _derived_requirement_source(builder.context)
            statement = f"系统应{subject}"
            derived = builder.add(
                EntityKind.REQUIREMENT,
                statement,
                {
                    "statement": statement,
                    "source": "derived_from_existing_model",
                    "derived_from_kind": source.kind.value if source else "",
                    "source_context_ids": [source.id] if source else [],
                    "level": "system",
                    "type": "functional",
                    "obligation": "系统应",
                    "verification_method": "test",
                    "derived_by": "system_requirement_derivation",
                },
            )
            if source is not None:
                builder.relate(derived, RelationPredicate.DERIVED_FROM, source)
            requirements = (derived,)
        domain = _domain_label(requirements) or builder.context.project_id
        system = _context_first(builder.context, EntityKind.SYSTEM) or builder.add(
            EntityKind.SYSTEM, f"{domain}系统", _system_payload(domain)
        )
        stakeholder = _context_first(builder.context, EntityKind.STAKEHOLDER) or builder.add(
            EntityKind.STAKEHOLDER, "系统使用者", {"role": "使用与验收"}
        )
        concern = _context_first(builder.context, EntityKind.CONCERN) or builder.add(
            EntityKind.CONCERN, f"{domain}可靠性与运营可用性", {
                "topic": f"在正常、异常和人工接管场景下完成可追踪{domain}任务",
                "stakeholder_ids": [stakeholder.id],
            }
        )
        scenario = _context_first(builder.context, EntityKind.OPERATIONAL_SCENARIO) or builder.add(
            EntityKind.OPERATIONAL_SCENARIO, f"典型{domain}运行场景", {
                "actor_ids": [stakeholder.id],
                "steps": [f"提出{domain}任务", f"系统执行{domain}任务", "反馈结果"],
                "exchanges": [],
                "internal_component_ids": [],
            }
        )
        lifecycle = _context_first(builder.context, EntityKind.LIFECYCLE_STAGE) or builder.add(
            EntityKind.LIFECYCLE_STAGE, "设计—运行生命周期", {
                "stage": "operation",
                "sequence": ["设计", "部署", "运行", "维护"],
                "exit_criteria": "进入可持续运行和维护",
            }
        )
        transitions = []
        for source, target in (("设计", "部署"), ("部署", "运行"), ("运行", "维护")):
            transition = _existing_lifecycle_transition(builder, source, target)
            if transition is None:
                transition = builder.add(
                    EntityKind.LIFECYCLE_TRANSITION,
                    f"生命周期转移：{source}→{target}",
                    {
                        "from_stage": source,
                        "to_stage": target,
                        "trigger": f"完成{source}阶段退出准则",
                        "guard": "满足进入下一阶段的工程条件",
                    },
                )
            transitions.append(transition)
        hypothesis = _context_first(builder.context, EntityKind.SCENARIO_HYPOTHESIS) or builder.add(
            EntityKind.SCENARIO_HYPOTHESIS, f"典型{domain}场景假设", {
                "category": "normal",
                "actors": [stakeholder.meta.name],
                "trigger": f"运营人员提交{domain}任务",
                "outcome": f"{domain}任务完成并反馈结果",
            }
        )
        use_case = _context_first(builder.context, EntityKind.USE_CASE) or builder.add(
            EntityKind.USE_CASE, f"执行一次{domain}任务", {
                "primary_actor": stakeholder.meta.name,
                "goal": f"完成可追踪{domain}",
                "success": "接收结果并可人工接管",
            }
        )
        activity = _context_first(builder.context, EntityKind.ACTIVITY) or builder.add(
            EntityKind.ACTIVITY, f"受理并完成{domain}活动", {
                "steps": [f"受理{domain}任务", "规划执行", f"完成{domain}", "反馈结果"],
                "branches": ["人工接管", "任务失败后重试"],
            }
        )
        builder.relate(stakeholder, RelationPredicate.HAS_CONCERN, concern)
        builder.relate(system, RelationPredicate.DECOMPOSES, stakeholder)
        builder.relate(stakeholder, RelationPredicate.PARTICIPATES_IN, scenario)
        builder.relate(stakeholder, RelationPredicate.DERIVED_FROM, hypothesis)
        builder.relate(use_case, RelationPredicate.DERIVED_FROM, hypothesis)
        builder.relate(scenario, RelationPredicate.DERIVED_FROM, use_case)
        builder.relate(activity, RelationPredicate.OCCURS_IN, lifecycle)
        for transition in transitions:
            builder.relate(transition, RelationPredicate.DERIVED_FROM, lifecycle)
        for requirement in requirements:
            requirement_payload = dict(requirement.payload)
            requirement_payload.setdefault(
                "derived_by", "system_requirement_derivation"
            )
            if requirement.id in builder.index:
                builder.update(requirement, payload=requirement_payload)
            builder.relate(requirement, RelationPredicate.DERIVED_FROM, concern)
            builder.relate(requirement, RelationPredicate.DERIVED_FROM, activity)
        return builder.response()

    def _functional(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        requirements = _requirements(request)
        domain = _domain_label(requirements) or builder.context.project_id
        for requirement in requirements:
            source_context_ids = _source_context_ids(requirement)
            function = next(
                (
                    item for item in _context_entities(
                        request.context_bundle, EntityKind.FUNCTION
                    )
                    if item.id in source_context_ids
                ),
                None,
            )
            if function is None:
                function = _related_context_entity(
                    request.context_bundle,
                    requirement.id,
                    RelationPredicate.SATISFIED_BY,
                    EntityKind.FUNCTION,
                )
            function_name = f"执行：{_requirement_text(requirement)[:36]}"
            function_payload = {
                "behavior": f"实现{_requirement_text(requirement)}",
                "inputs": [],
                "outputs": ["执行结果"],
                "decomposition": [
                    f"解析{_requirement_text(requirement)}",
                    f"执行{_requirement_text(requirement)}",
                    "产生并反馈结果",
                ],
                "source_requirement_id": requirement.id,
                "source_context_ids": sorted(source_context_ids),
            }
            if function is None:
                function = builder.add(EntityKind.FUNCTION, function_name, function_payload)
            else:
                builder.update(function, name=function_name, payload=function_payload)
            builder.relate(requirement, RelationPredicate.SATISFIED_BY, function)
        functions = _builder_entities(builder, EntityKind.FUNCTION)
        for requirement in requirements:
            function_ids = [
                function.id
                for function in functions
                if function.payload.get("source_requirement_id") == requirement.id
            ]
            if not function_ids:
                function_ids = [
                    relation.target_id
                    for relation in request.context_bundle.relations
                    if relation.source_id == requirement.id
                    and relation.predicate is RelationPredicate.SATISFIED_BY
                    and relation.target_id in {function.id for function in functions}
                ]
            requirement_payload = dict(requirement.payload)
            requirement_payload.update({
                "functional_behavior_ids": sorted(set(function_ids)),
                "functional_requirement_status": "allocated",
            })
            builder.update(requirement, payload=requirement_payload)
        function_ids = [item.id for item in functions]
        flow_payload = {
            "direction": "双向",
            "content": f"{domain}任务与结果",
            "source_function_ids": function_ids[:1],
            "target_function_ids": function_ids[1:] or function_ids[:1],
        }
        flow = next(
            (
                item for item in _context_entities(
                    request.context_bundle, EntityKind.FUNCTIONAL_FLOW
                )
                if any(
                    relation.source_id in {function.id for function in functions}
                    and relation.predicate is RelationPredicate.EXCHANGES_WITH
                    and relation.target_id == item.id
                    for relation in request.context_bundle.relations
                )
            ),
            None,
        )
        if flow is None:
            flow = builder.add(EntityKind.FUNCTIONAL_FLOW, f"{domain}信息交互流", flow_payload)
        else:
            builder.update(flow, payload=flow_payload)
        scenario_payload = {
            "function_ids": [item.id for item in functions],
            "steps": ["输入", "处理", "输出"],
        }
        scenario = next(
            (
                item for item in _context_entities(
                    request.context_bundle, EntityKind.FUNCTIONAL_SCENARIO
                )
                if any(
                    relation.source_id in {function.id for function in functions}
                    and relation.predicate is RelationPredicate.DERIVED_FROM
                    and relation.target_id == item.id
                    for relation in request.context_bundle.relations
                )
            ),
            None,
        )
        if scenario is None:
            scenario = builder.add(
                EntityKind.FUNCTIONAL_SCENARIO,
                f"完成{domain}核心功能场景",
                scenario_payload,
            )
        else:
            builder.update(scenario, payload=scenario_payload)
        for function in functions:
            builder.relate(function, RelationPredicate.EXCHANGES_WITH, flow)
            builder.relate(function, RelationPredicate.DERIVED_FROM, scenario)
        return builder.response()

    def _logical(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        decision = _controller_decision(request.context_bundle)
        option = str(decision.get("option", "")).strip()
        variant = option if option in _LOGICAL_VARIANTS else ""
        domain = _domain_label(_requirements(request)) or "配送"
        functions = _context_entities(request.context_bundle, EntityKind.FUNCTION)
        if variant:
            existing_variant = next(
                (
                    item for item in _context_entities(
                        request.context_bundle, EntityKind.LOGICAL_COMPONENT
                    )
                    if item.payload.get("architecture_variant") == variant
                ),
                None,
            )
            if existing_variant is not None:
                return builder.response()
        groups, blocked = _logical_groups(builder, functions, variant)
        flow_evidence = _functional_flow_evidence(
            request.context_bundle, functions
        )
        synthesis = synthesize_architecture(_context_graph(request.context_bundle))
        function_component_index = {
            function.id: index
            for index, group in enumerate(groups)
            for function in group
        }
        logical_components = _build_logical_components(
            builder,
            domain,
            functions,
            groups,
            variant,
            decision,
            blocked,
            flow_evidence,
            function_component_index,
            synthesis,
        )
        if not logical_components:
            return builder.response()
        suffix = f"（{variant}）" if variant else ""
        state_payload = {
            "values": ["待受理", "执行中", "人工接管", "完成", "失败"],
            "transitions": [
                "待受理->执行中", "执行中->人工接管", "执行中->完成",
                "执行中->失败", "失败->执行中",
            ],
            "owner_id": logical_components[0].id,
            "owner_ids": [item.id for item in logical_components],
        }
        state = _related_context_entity(
            request.context_bundle,
            logical_components[0].id,
            RelationPredicate.DECOMPOSES,
            EntityKind.STATE,
        )
        if state is None:
            state = builder.add(EntityKind.STATE, f"{domain}任务状态{suffix}", state_payload)
        else:
            builder.update(state, payload=state_payload)
        interface_payload = {
            "protocol": "logical-message",
            "exchanges": ["task_request", "task_status", "handover"],
            "connected_component_ids": [item.id for item in logical_components],
        }
        interface = _related_context_entity(
            request.context_bundle,
            logical_components[0].id,
            RelationPredicate.CONNECTED_TO,
            EntityKind.INTERFACE,
        )
        if interface is None:
            interface = builder.add(
                EntityKind.INTERFACE,
                f"{domain}任务交互接口{suffix}",
                interface_payload,
            )
        else:
            builder.update(interface, payload=interface_payload)
        for logical in logical_components:
            builder.relate(logical, RelationPredicate.CONNECTED_TO, interface)
            builder.relate(logical, RelationPredicate.DECOMPOSES, state)
        for group, logical in zip(groups, logical_components):
            for function in group:
                builder.relate(function, RelationPredicate.ALLOCATED_TO, logical)
        for function in functions:
            builder.relate(function, RelationPredicate.EXCHANGES_WITH, interface)
        return builder.response()

    def _physical(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        physical_entities = []
        decision = _controller_decision(request.context_bundle)
        option = str(decision.get("option", "")).strip()
        physical_variant = option if option in _PHYSICAL_VARIANTS else ""
        domain = _domain_label(_requirements(request)) or "配送"
        logical_components = _context_entities(request.context_bundle, EntityKind.LOGICAL_COMPONENT)
        for logical in logical_components:
            functions = tuple(
                item for item in _context_entities(request.context_bundle, EntityKind.FUNCTION)
                if any(
                    relation.source_id == item.id
                    and relation.predicate is RelationPredicate.ALLOCATED_TO
                    and relation.target_id == logical.id
                    for relation in request.context_bundle.relations
                )
            )
            requirements = _requirements_for_functions(request.context_bundle, functions)
            linked_physical = next(
                (
                    candidate for candidate in _context_entities(
                        request.context_bundle, EntityKind.PHYSICAL_BLOCK
                    )
                    if any(
                        relation.source_id == logical.id
                        and relation.predicate is RelationPredicate.ALLOCATED_TO
                        and relation.target_id == candidate.id
                        for relation in request.context_bundle.relations
                    ) or candidate.id in _source_context_ids(logical)
                ),
                None,
            )
            name = (
                linked_physical.meta.name
                if linked_physical is not None and not physical_variant
                else f"{domain}协同执行平台"
                if len(logical_components) == 1
                else f"{logical.meta.name}执行平台"
            )
            payload = _physical_payload_with_reasoning(logical, requirements, linked_physical)
            if (
                linked_physical is not None
                and linked_physical.meta.status is not EntityStatus.LOCKED
                and not bool(linked_physical.payload.get("user_modified"))
            ):
                payload.update({
                    field: linked_physical.payload[field]
                    for field in _PHYSICAL_MEASUREMENT_FIELDS
                    if field in linked_physical.payload
                    and linked_physical.payload[field] not in (None, "", [], {})
                })
            conflicts = _physical_constraint_conflicts(payload, requirements)
            if conflicts:
                payload["feasibility"] = {
                    **dict(payload.get("feasibility", {})),
                    "status": "infeasible",
                    "conflicts": conflicts,
                }
            if not any(_explicit_constraint_map(item) for item in requirements):
                payload["technical_requirement_status"] = "no_explicit_constraints"
            if physical_variant == "更换物理候选或计算架构":
                name = f"{name}替代候选"
                _set_physical_reasoning_scope(
                    payload, logical, functions, requirements,
                    make_entity(EntityKind.PHYSICAL_BLOCK, name).id,
                    conflicts,
                )
                payload.update({
                    "candidate_variant": "alternative",
                    "architecture_decision": dict(_decision_payload(decision)),
                    "open_questions": ["替代物理候选的 SWaP-C 需要测量并重新验证"],
                })
                physical = builder.add(EntityKind.PHYSICAL_BLOCK, name, payload)
            else:
                existing = builder.find(EntityKind.PHYSICAL_BLOCK, name)
                if existing is None and physical_variant:
                    payload.update({
                        "architecture_decision": dict(_decision_payload(decision)),
                        "open_questions": ["需要用户/利益相关者确认该 Trade Study 决策并重新验证"],
                    })
                _set_physical_reasoning_scope(
                    payload, logical, functions, requirements,
                    existing.id if existing is not None
                    else make_entity(EntityKind.PHYSICAL_BLOCK, name).id,
                    conflicts,
                )
                physical = existing or builder.add(EntityKind.PHYSICAL_BLOCK, name, payload)
                if existing is not None and not physical_variant:
                    builder.update(physical, payload=payload)
                if physical_variant and existing is not None and not _same_decision(existing, decision):
                    decision_fields = {
                        "architecture_decision": dict(_decision_payload(decision)),
                        "open_questions": ["需要用户/利益相关者确认该 Trade Study 决策并重新验证"],
                    }
                    if not builder.update_payload(
                        physical, {**dict(physical.payload), **decision_fields}
                    ):
                        alternative_payload = {
                            **payload,
                            "candidate_variant": "alternative",
                            "architecture_decision": dict(_decision_payload(decision)),
                            "blocked_by_locked_entity": True,
                            "open_questions": ["替代物理候选的 SWaP-C 需要测量并重新验证"],
                        }
                        physical = builder.add(
                            EntityKind.PHYSICAL_BLOCK,
                            f"{name}替代候选",
                            alternative_payload,
                        )
            _record_physical_entity(builder, physical_entities, logical, physical)
            for requirement in requirements:
                requirement_payload = dict(requirement.payload)
                requirement_payload["feasibility_review"] = {
                    "status": "needs_measurement",
                    "measured_values": None,
                    "physical_candidate_ids": [physical.id],
                }
                builder.update(requirement, payload=requirement_payload)
            for requirement in requirements:
                constraints = _explicit_constraint_map(requirement)
                if not constraints:
                    continue
                technical_payload = _technical_requirement_payload(
                    requirement, physical, constraints
                )
                technical = next(
                    (
                        item for item in _context_entities(
                            request.context_bundle, EntityKind.REQUIREMENT
                        )
                        if item.payload.get("level") == "technical"
                        and requirement.id in item.payload.get("source_requirement_ids", ())
                        and physical.id in item.payload.get("source_physical_ids", ())
                    ),
                    None,
                )
                if technical is None:
                    technical = builder.add(
                        EntityKind.REQUIREMENT,
                        f"{physical.meta.name}技术约束：{requirement.meta.name[:24]}",
                        technical_payload,
                    )
                else:
                    builder.update(technical, payload=technical_payload)
                builder.relate(technical, RelationPredicate.DERIVED_FROM, requirement)
                builder.relate(technical, RelationPredicate.SATISFIED_BY, physical)
        _persist_physical_reasoning(builder, physical_entities)
        return builder.response()

    def _verification_validation(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        activities = _context_entities(request.context_bundle, EntityKind.ACTIVITY)
        scenario_ids = [
            item.id for item in request.context_bundle.entities
            if item.kind in {
                EntityKind.OPERATIONAL_SCENARIO,
                EntityKind.FUNCTIONAL_SCENARIO,
            }
        ]
        branch_names = [
            branch
            for activity in activities
            for branch in activity.payload.get("branches", ())
            if str(branch).strip()
        ]
        activity_ids = [item.id for item in activities]
        for requirement in _requirements(request):
            trace_scope = _requirement_trace_scope(request.context_bundle, requirement)
            verification = _related_context_entity(
                request.context_bundle,
                requirement.id,
                RelationPredicate.VERIFIED_BY,
                EntityKind.VERIFICATION_CASE,
            )
            verification_payload = _vertical_vv_plan_payload(
                "verification", requirement, trace_scope, scenario_ids,
                activity_ids, branch_names, verification,
            )
            if verification is None:
                verification = builder.add(
                    EntityKind.VERIFICATION_CASE,
                    f"验证：{_requirement_text(requirement)[:32]}",
                    verification_payload,
                )
            else:
                builder.update(
                    verification,
                    name=f"验证：{_requirement_text(requirement)[:32]}",
                    payload={**dict(verification.payload), **verification_payload},
                )
            validation = _related_context_entity(
                request.context_bundle,
                requirement.id,
                RelationPredicate.VALIDATED_BY,
                EntityKind.VALIDATION_CASE,
            )
            validation_payload = _vertical_vv_plan_payload(
                "validation", requirement, trace_scope, scenario_ids,
                activity_ids, branch_names, validation,
            )
            if validation is None:
                validation = builder.add(
                    EntityKind.VALIDATION_CASE,
                    f"确认：{_requirement_text(requirement)[:32]}",
                    validation_payload,
                )
            else:
                builder.update(
                    validation,
                    name=f"确认：{_requirement_text(requirement)[:32]}",
                    payload={**dict(validation.payload), **validation_payload},
                )
            hazard_payload = {
                "description": "异常分支、资源异常或人工接管不当导致任务目标未达成",
                "requirement_ids": [requirement.id],
                "activity_ids": activity_ids,
                "branches": branch_names,
            }
            hazard = _related_context_entity(
                request.context_bundle,
                requirement.id,
                RelationPredicate.DERIVED_FROM,
                EntityKind.HAZARD,
                reverse=True,
            )
            if hazard is None:
                hazard = builder.add(
                    EntityKind.HAZARD,
                    f"风险：{_requirement_text(requirement)[:28]}",
                    hazard_payload,
                )
            else:
                builder.update(
                    hazard,
                    name=f"风险：{_requirement_text(requirement)[:28]}",
                    payload=hazard_payload,
                )
            failure_payload = {
                "effect": "需求未满足或任务结果不可追踪",
                "cause": "执行条件、资源或交互异常",
                "requirement_ids": [requirement.id],
                "activity_ids": activity_ids,
            }
            failure_mode = _related_context_entity(
                request.context_bundle,
                hazard.id,
                RelationPredicate.CAUSES,
                EntityKind.FAILURE_MODE,
            )
            if failure_mode is None:
                failure_mode = builder.add(
                    EntityKind.FAILURE_MODE,
                    f"失效模式：{_requirement_text(requirement)[:28]}",
                    failure_payload,
                )
            else:
                builder.update(
                    failure_mode,
                    name=f"失效模式：{_requirement_text(requirement)[:28]}",
                    payload=failure_payload,
                )
            builder.relate(requirement, RelationPredicate.VERIFIED_BY, verification)
            builder.relate(requirement, RelationPredicate.VALIDATED_BY, validation)
            builder.relate(hazard, RelationPredicate.DERIVED_FROM, requirement)
            builder.relate(hazard, RelationPredicate.CAUSES, failure_mode)
            builder.relate(hazard, RelationPredicate.MITIGATED_BY, verification)
            builder.relate(failure_mode, RelationPredicate.MITIGATED_BY, verification)
        return builder.response()


def _vertical_vv_plan_payload(
    case_type, requirement, trace_scope, scenario_ids, activity_ids,
    branch_names, existing=None,
):
    evidence_ids = list(requirement.meta.evidence_ids)
    execution_evidence_ids = []
    if existing is not None:
        evidence_ids = list(dict.fromkeys(
            (*existing.payload.get("evidence_ids", ()), *evidence_ids)
        ))
        execution_evidence_ids = list(existing.payload.get("execution_evidence_ids", ()))
    text = _requirement_text(requirement)
    is_verification = case_type == "verification"
    payload = {
        "method": "test" if is_verification else "demonstration",
        "verification_objective": (
            f"证明需求“{text}”在规定条件下满足"
            if is_verification else f"确认用户场景目标“{text}”实际达成"
        ),
        "precondition": (
            "系统处于可测试初始状态"
            if is_verification else "目标用户和典型场景可用"
        ),
        "test_condition": (
            "标准运行环境、额定负载和需求边界条件"
            if is_verification else "典型用户、真实运行场景和代表性任务条件"
        ),
        "input": text,
        "stimulus": (
            "提交需求并施加正常、异常及人工接管事件"
            if is_verification else "由运营人员执行任务并触发必要的用户操作"
        ),
        "procedure": (
            "执行测试步骤并记录实际结果"
            if is_verification else "在典型场景执行并收集用户反馈"
        ),
        "expected_result": (
            "实际结果满足需求目标"
            if is_verification else "用户场景目标达成"
        ),
        "pass_criteria": (
            f"测试结果满足：{text}"
            if is_verification else f"用户场景确认：{text}"
        ),
        "evidence_ids": evidence_ids,
        "execution_evidence_ids": execution_evidence_ids,
        "requirement_ids": [requirement.id],
        "scenario_ids": scenario_ids,
        "activity_ids": activity_ids,
        "covered_branches": branch_names,
        "function_ids": trace_scope["function_ids"],
        "logical_component_ids": trace_scope["logical_component_ids"],
        "physical_ids": trace_scope["physical_ids"],
        "constraint_fields": sorted(_explicit_constraint_map(requirement)),
        "evidence_required": not bool(execution_evidence_ids),
        "open_questions": (
            [] if execution_evidence_ids else [
                "执行证据待补充；计划字段完整不代表测试已通过"
                if is_verification else
                "演示或用户确认依据待补充；计划字段完整不代表确认已通过"
            ]
        ),
    }
    if is_verification:
        payload["cross_analysis_status"] = "checked"
    return payload


def _logical_groups(builder, functions, variant):
    groups = _partition_functions(functions, builder.context.relations)
    if variant == "one_component_per_function":
        groups = tuple((function,) for function in functions)
    elif variant == "shared_coordinator" and functions:
        groups = (tuple(functions),)
    elif variant == "dependency_cluster_search":
        groups = _partition_functions(functions, builder.context.relations)
    blocked = False
    if variant:
        for item in builder.context.entities:
            if item.kind not in {
                EntityKind.LOGICAL_COMPONENT,
                EntityKind.INTERFACE,
                EntityKind.STATE,
            }:
                continue
            if item.meta.status is EntityStatus.LOCKED or bool(item.payload.get("user_modified")):
                blocked = True
                continue
            builder.deprecate(item)
    return groups, blocked


def _build_logical_components(
    builder,
    domain,
    functions,
    groups,
    variant,
    decision,
    blocked,
    flow_evidence,
    function_component_index,
    synthesis,
):
    components = []
    for group in groups:
        payload = _logical_component_payload(
            domain,
            group,
            groups,
            variant,
            decision,
            blocked,
            flow_evidence,
            function_component_index,
            functions,
            synthesis,
        )
        label = _partition_label(group)
        base_name = (
            f"{domain}协同逻辑架构"
            if len(groups) == 1 and len(group) == 1
            else f"{group[0].meta.name}逻辑组件"
            if variant == "one_component_per_function" and len(group) == 1
            else f"{label}逻辑组件"
        )
        name = f"{base_name}（{variant}）" if variant else base_name
        existing = _existing_logical_for_group(builder.context, group) if not variant else None
        logical = existing or builder.add(EntityKind.LOGICAL_COMPONENT, name, payload)
        if existing is not None:
            builder.update(logical, name=name, payload=payload)
        components.append(logical)
    return tuple(components)


def _logical_component_payload(
    domain,
    group,
    groups,
    variant,
    decision,
    blocked,
    flow_evidence,
    function_component_index,
    functions,
    synthesis,
):
    label = _partition_label(group)
    group_ids = {item.id for item in group}
    dependency_evidence = sorted({
        target.id
        for function in group
        for target in _resolved_function_dependencies(function, functions)
        if target.id in group_ids
    })
    functional_flow_ids = sorted({
        item["flow_id"]
        for item in flow_evidence
        if group_ids & set(item["function_ids"])
    })
    cross_component_flow_ids = _cross_component_flow_ids(
        group_ids, flow_evidence, function_component_index
    )
    shared_state = _union_payload_values(group, "shared_state") or [f"{domain}任务状态"]
    timing_constraints = _union_payload_values(group, "timing_constraints") or [f"{domain}任务状态更新必须可排序"]
    partition_basis = _partition_basis(group, dependency_evidence)
    payload = {
        "responsibility": "；".join(
            str(item.payload.get("behavior") or item.meta.name)
            for item in group
        ),
        "partition_basis": f"按 {label} 的{partition_basis}形成分区",
        "dependencies": [item.id for item in group],
        "dependency_evidence": dependency_evidence,
        "functional_flow_ids": functional_flow_ids,
        "cross_component_flow_ids": cross_component_flow_ids,
        "shared_state": shared_state,
        "timing_constraints": timing_constraints,
        "safety_isolation": ["人工接管路径与自动执行路径隔离"],
        "source_context_ids": sorted({
            source_id
            for function in group
            for source_id in _source_context_ids(function)
        }),
        "cohesion": "high",
        "coupling": "high"
        if cross_component_flow_ids
        else "controlled"
        if len(group) == 1
        else "high",
        "interfaces": [],
        "alternative_partitions": [
            "one_component_per_function",
            "dependency_cluster_search",
            "shared_coordinator",
        ],
        "architecture_rationale": _architecture_rationale(
            group, dependency_evidence, cross_component_flow_ids
        ),
        "architecture_reasoning": logical_reasoning_payload(
            synthesis,
            function_ids=[item.id for item in group],
            functional_flow_ids=functional_flow_ids,
            dependency_pairs=_dependency_pairs(group, functions),
            shared_state=shared_state,
            timing_constraints=timing_constraints,
            selected_alternative=variant,
            selection_status="selected" if variant else "needs_review",
            names={item.id: item.meta.name for item in functions},
        ),
    }
    if variant:
        payload.update({
            "architecture_variant": variant,
            "architecture_decision": dict(_decision_payload(decision)),
        })
        if blocked:
            payload["blocked_by_locked_entity"] = True
    return payload


def _partition_basis(group, dependency_evidence):
    if dependency_evidence:
        return "显式功能依赖"
    if _union_payload_values(group, "shared_state"):
        return "共享状态"
    if any(
        str(item.payload.get("logical_partition") or item.payload.get("partition_key") or "").strip()
        for item in group
    ):
        return "显式分区键"
    return "功能职责"


def _cross_component_flow_ids(group_ids, flow_evidence, function_component_index):
    return sorted({
        item["flow_id"]
        for item in flow_evidence
        if group_ids & set(item["function_ids"])
        and any(
            function_component_index.get(source_id)
            != function_component_index.get(target_id)
            for source_id in item["source_function_ids"]
            for target_id in item["target_function_ids"]
            if source_id in function_component_index
            and target_id in function_component_index
        )
    })


def _architecture_rationale(group, dependency_evidence, cross_component_flow_ids):
    if dependency_evidence:
        rationale = "显式功能依赖支持同一逻辑边界"
    elif len(group) == 1:
        rationale = "单一功能职责保持边界清晰"
    else:
        rationale = "共享状态使功能保持在同一逻辑边界，但需要评审耦合"
    if cross_component_flow_ids:
        rationale += "；功能流跨越该边界，需要通过接口管理"
    return rationale


def _partition_functions(functions, relations=()):
    functions = tuple(functions)
    function_by_id = {item.id: item for item in functions}
    function_by_name = {item.meta.name: item for item in functions}
    parent = {item.id: item.id for item in functions}

    def find(entity_id):
        while parent[entity_id] != entity_id:
            parent[entity_id] = parent[parent[entity_id]]
            entity_id = parent[entity_id]
        return entity_id

    def union(first_id, second_id):
        first_root = find(first_id)
        second_root = find(second_id)
        if first_root != second_root:
            parent[second_root] = first_root

    keyed: dict[object, list[str]] = {}
    for function in functions:
        payload = function.payload
        explicit = str(
            payload.get("logical_partition") or payload.get("partition_key") or ""
        ).strip()
        shared = payload.get("shared_state")
        shared_values = (
            tuple(sorted(str(item).strip() for item in shared if str(item).strip()))
            if isinstance(shared, (list, tuple))
            else ()
        )
        key = (
            ("explicit", explicit)
            if explicit
            else ("shared", shared_values)
            if shared_values
            else ("function", function.id)
        )
        keyed.setdefault(key, []).append(function.id)
        for target in _resolved_function_dependencies(function, functions):
            union(function.id, target.id)
    for ids in keyed.values():
        for target_id in ids[1:]:
            union(ids[0], target_id)
    for relation in relations:
        if relation.predicate is RelationPredicate.DECOMPOSES:
            if relation.source_id in function_by_id and relation.target_id in function_by_id:
                union(relation.source_id, relation.target_id)
    groups: dict[str, list[object]] = {}
    for function in functions:
        groups.setdefault(find(function.id), []).append(function)
    return tuple(tuple(group) for group in groups.values())


def _resolved_function_dependencies(function, functions):
    by_id = {item.id: item for item in functions}
    by_name = {item.meta.name: item for item in functions}
    references = []
    for key in ("dependencies", "depends_on", "dependency_ids", "depends_on_ids"):
        raw = function.payload.get(key)
        if isinstance(raw, str):
            raw = (raw,)
        if isinstance(raw, (list, tuple, set)):
            references.extend(str(item).strip() for item in raw if str(item).strip())
    resolved = []
    for reference in references:
        target = by_id.get(reference) or by_name.get(reference)
        if target is not None and target.id != function.id:
            resolved.append(target)
    return tuple({item.id: item for item in resolved}.values())


def _functional_flow_evidence(context, functions):
    function_by_id = {item.id: item for item in functions}
    function_by_name = {item.meta.name: item for item in functions}
    function_ids = set(function_by_id)
    evidence = []
    for flow in _context_entities(context, EntityKind.FUNCTIONAL_FLOW):
        source_ids = _resolve_function_values(
            flow.payload.get("source_function_ids"), function_by_id, function_by_name
        )
        target_ids = _resolve_function_values(
            flow.payload.get("target_function_ids"), function_by_id, function_by_name
        )
        if not source_ids or not target_ids:
            members = sorted({
                relation.source_id
                for relation in context.relations
                if relation.predicate is RelationPredicate.EXCHANGES_WITH
                and relation.target_id == flow.id
                and relation.source_id in function_ids
            })
            source_ids = tuple(members[:1])
            target_ids = tuple(members[1:] or members[:1])
        endpoint_ids = tuple(dict.fromkeys((*source_ids, *target_ids)))
        if endpoint_ids:
            evidence.append({
                "flow_id": flow.id,
                "function_ids": endpoint_ids,
                "source_function_ids": source_ids,
                "target_function_ids": target_ids,
            })
    return tuple(evidence)


def _resolve_function_values(raw, by_id, by_name):
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, (list, tuple, set)):
        return ()
    resolved = []
    for value in raw:
        target = by_id.get(str(value).strip()) or by_name.get(str(value).strip())
        if target is not None:
            resolved.append(target.id)
    return tuple(dict.fromkeys(resolved))


def _partition_label(group):
    first = group[0]
    payload = first.payload
    explicit = str(
        payload.get("logical_partition") or payload.get("partition_key") or ""
    ).strip()
    if explicit:
        return explicit
    shared = payload.get("shared_state")
    if isinstance(shared, (list, tuple)):
        values = tuple(str(item).strip() for item in shared if str(item).strip())
        if values:
            return "共享状态：" + "、".join(values)
    return first.meta.name[:32]


def _union_payload_values(entities, key):
    values = []
    for entity in entities:
        raw = entity.payload.get(key)
        if isinstance(raw, (list, tuple)):
            values.extend(str(item).strip() for item in raw if str(item).strip())
    return list(dict.fromkeys(values))


def _requirements_for_functions(context, functions):
    function_ids = {item.id for item in functions}
    requirement_ids = {
        relation.source_id
        for relation in context.relations
        if relation.predicate is RelationPredicate.SATISFIED_BY
        and relation.target_id in function_ids
    }
    return tuple(
        item for item in context.entities
        if item.kind is EntityKind.REQUIREMENT and item.id in requirement_ids
    )


def _explicit_constraint_map(requirement):
    constraints = {}
    for key, value in requirement.payload.items():
        key = str(key)
        if key.startswith(("max_", "min_")):
            constraints[key] = value
    for container_key in ("constraints", "limits"):
        container = requirement.payload.get(container_key)
        if isinstance(container, Mapping):
            for key, value in container.items():
                key = str(key)
                if key.startswith(("max_", "min_")):
                    constraints[key] = value
    return dict(sorted(constraints.items()))


def _technical_requirement_payload(requirement, physical, constraints):
    provenance = requirement.payload.get("constraint_provenance")
    return {
        "level": "technical",
        "type": "constraint",
        "statement": f"物理候选“{physical.meta.name}”应满足需求“{requirement.meta.name}”中的显式工程约束",
        "obligation": "物理候选应满足显式工程约束",
        "verification_method": "test",
        "constraint_fields": list(constraints),
        "constraints": dict(constraints),
        "source_requirement_ids": [requirement.id],
        "source_physical_ids": [physical.id],
        "constraint_provenance": [
            item for item in provenance if isinstance(item, Mapping)
        ] if isinstance(provenance, list) else [],
        "open_questions": ["需要对该物理候选执行工程约束验证"],
    }


def _context_first(context, kind: EntityKind):
    return next((item for item in context.entities if item.kind is kind), None)


def _context_entities(context, kind: EntityKind):
    return tuple(item for item in context.entities if item.kind is kind)


def _context_graph(context):
    return ModelGraph(
        context.project_id,
        tuple(context.entities),
        tuple(context.relations),
        context.revision,
    )


def _dependency_pairs(group, functions):
    group_ids = {item.id for item in group}
    pairs = set()
    for function in group:
        for target in _resolved_function_dependencies(function, functions):
            if target.id in group_ids:
                pairs.add(tuple(sorted((function.id, target.id))))
    shared_members: dict[str, list[str]] = {}
    for function in group:
        values = function.payload.get("shared_state")
        if not isinstance(values, (list, tuple, set)):
            continue
        for value in values:
            state = str(value).strip()
            if state:
                shared_members.setdefault(state, []).append(function.id)
    for members in shared_members.values():
        pairs.update(
            tuple(sorted(pair))
            for pair in combinations(sorted(set(members)), 2)
        )
    return tuple(sorted(pairs))


def _persist_physical_reasoning(builder, physical_entities):
    unique_entities = {
        item.id: item for item in physical_entities if item is not None
    }
    if not unique_entities or not builder.operations:
        return
    preview_patch = Patch.create(
        builder.context.project_id,
        f"{builder.request.task_id}.reasoning-preview",
        tuple(builder.operations),
        "生成物理可行性推理预览",
        builder.context.revision,
    )
    preview = apply_patch(_context_graph(builder.context), preview_patch)
    rows = {
        row.physical_id: row
        for row in synthesize_architecture(preview).physical_rows
    }
    for physical_id in sorted(unique_entities):
        current = preview.entity_index.get(physical_id)
        row = rows.get(physical_id)
        if current is None or row is None:
            continue
        payload = dict(current.payload)
        payload["feasibility_reasoning"] = physical_reasoning_payload(row)
        if physical_id in builder.added:
            updated = make_entity(
                EntityKind.PHYSICAL_BLOCK,
                current.meta.name,
                payload,
                status=current.meta.status,
                producer=current.meta.producer,
                confidence=current.meta.confidence,
                source_ids=current.meta.source_ids,
                evidence_ids=current.meta.evidence_ids,
                lifecycle_ids=current.meta.lifecycle_ids,
                revision=builder.context.revision,
            )
            if updated.id != physical_id:
                raise ValueError("physical reasoning changed the canonical physical id")
            builder.added[physical_id] = updated
            builder.operations = [
                AddEntity(updated)
                if isinstance(operation, AddEntity) and operation.entity.id == physical_id
                else operation
                for operation in builder.operations
            ]
        else:
            builder.update(current, payload=payload)


def _related_context_entity(
    context,
    source_id: str,
    predicate: RelationPredicate,
    target_kind: EntityKind,
    *,
    reverse: bool = False,
):
    entities = {item.id: item for item in context.entities}
    for relation in context.relations:
        if relation.predicate is not predicate:
            continue
        if reverse:
            if relation.target_id != source_id:
                continue
            candidate = entities.get(relation.source_id)
        else:
            if relation.source_id != source_id:
                continue
            candidate = entities.get(relation.target_id)
        if candidate is not None and candidate.kind is target_kind:
            return candidate
    return None


def _requirement_text(requirement) -> str:
    text = " ".join(
        str(requirement.payload.get("statement") or requirement.meta.name).split()
    ).strip()
    return text or requirement.meta.name


def _controller_decision(context):
    for raw in reversed(context.controller_decisions):
        if isinstance(raw, Mapping):
            return raw
    return {}


def _decision_payload(decision: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "action_id": str(decision.get("action_id", "")),
        "option_id": str(decision.get("option_id", "")),
        "option": str(decision.get("option", "")),
        "task_id": str(decision.get("task_id", "")),
        "source_revision": int(decision.get("revision", 0) or 0),
    }


def _same_decision(entity, decision: Mapping[str, object]) -> bool:
    existing = entity.payload.get("architecture_decision")
    return (
        isinstance(existing, Mapping)
        and str(existing.get("option_id", "")) == str(decision.get("option_id", ""))
        and str(existing.get("option", "")) == str(decision.get("option", ""))
    )


def _builder_entities(builder: _VerticalPatchBuilder, kind: EntityKind):
    return tuple(
        item for item in tuple(builder.index.values()) + tuple(builder.added.values())
        if item.kind is kind
    )


def _requirements(request: TaskExecutionRequest):
    return tuple(
        item for item in request.context_bundle.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.meta.status is not EntityStatus.DEPRECATED
    )


def _source_context_ids(entity) -> set[str]:
    raw = entity.payload.get("source_context_ids", ())
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _existing_lifecycle_transition(builder, source: str, target: str):
    names = {
        f"生命周期转移：{source}→{target}",
        f"{source}→{target}",
        f"{source}到{target}",
    }
    for transition in _builder_entities(builder, EntityKind.LIFECYCLE_TRANSITION):
        if transition.meta.status is EntityStatus.DEPRECATED:
            continue
        if (
            str(transition.payload.get("from_stage", "")).strip() == source
            and str(transition.payload.get("to_stage", "")).strip() == target
        ) or transition.meta.name in names:
            return transition
    return None


def _existing_logical_for_group(context, group):
    source_ids = {
        source_id
        for function in group
        for source_id in _source_context_ids(function)
    }
    logicals = _context_entities(context, EntityKind.LOGICAL_COMPONENT)
    for logical in logicals:
        if logical.id in source_ids:
            return logical
    for function in group:
        for relation in context.relations:
            if (
                relation.source_id == function.id
                and relation.predicate is RelationPredicate.ALLOCATED_TO
                and any(logical.id == relation.target_id for logical in logicals)
            ):
                return next(logical for logical in logicals if logical.id == relation.target_id)
    return None


_DERIVATION_FIELDS: dict[EntityKind, tuple[str, ...]] = {
    EntityKind.ACTIVITY: ("goal", "objective", "purpose", "statement"),
    EntityKind.OPERATIONAL_SCENARIO: ("goal", "outcome", "objective", "statement"),
    EntityKind.USE_CASE: ("goal", "objective", "success", "statement"),
    EntityKind.SCENARIO_HYPOTHESIS: ("outcome", "goal", "objective", "statement"),
    EntityKind.SYSTEM: ("mission", "objective", "statement"),
    EntityKind.FUNCTION: ("behavior", "objective", "purpose", "statement"),
    EntityKind.LOGICAL_COMPONENT: ("responsibility", "objective", "purpose", "statement"),
    EntityKind.PHYSICAL_BLOCK: ("solution_class", "candidate_type", "purpose", "statement"),
}
_DERIVATION_PLACEHOLDERS = frozenset({"", "待确认", "候选", "unknown", "tbd"})


def _derived_requirement_source(context):
    """Select bounded semantic context for a requirement missing from a partial model."""

    for kind, fields in _DERIVATION_FIELDS.items():
        for entity in context.entities:
            if entity.kind is not kind or entity.meta.status is EntityStatus.DEPRECATED:
                continue
            for field in (*fields, "__name__"):
                raw = entity.meta.name if field == "__name__" else entity.payload.get(field)
                values = raw if isinstance(raw, (list, tuple)) else (raw,)
                for value in values:
                    text = " ".join(str(value or "").split()).strip(" ：:、—-\t\n")
                    if text.casefold() in _DERIVATION_PLACEHOLDERS:
                        continue
                    text = re.sub(r"^(?:系统)?\s*(?:应|需|需要|必须)\s*", "", text)
                    text = re.split(r"(?:；|;|。|！|!|？|\?)", text, maxsplit=1)[0]
                    text = text.strip(" ：:、—-\t\n")[:48]
                    if text and text.casefold() not in _DERIVATION_PLACEHOLDERS:
                        return text, entity
    return context.project_id, None


def _domain_label(requirements) -> str:
    """Extract a short input-derived subject for the offline model fallback."""

    if not requirements:
        return ""
    first = requirements[0]
    raw = str(first.payload.get("statement") or first.meta.name).strip()
    raw = re.sub(r"^(?:系统)?\s*(?:应|需|需要|必须)\s*", "", raw)
    raw = re.sub(r"^(?:支持|实现|能够|可以)\s*[:：]?\s*", "", raw)
    raw = re.split(r"(?:并且|并|且|以及|；|;|。|，|,)", raw, maxsplit=1)[0]
    label = raw.strip(" ：:、—-\t\n")
    return label[:24]


def _system_payload(seed: str) -> Mapping[str, object]:
    return {
        "mission": f"完成{seed}",
        "system_boundary": {"inside": ["核心服务能力"], "outside": ["运行环境"]},
        "objectives": [f"满足{seed}"],
        "environment_assumptions": ["运行环境可用"],
        "exclusions": ["不预设具体厂商"],
        "open_questions": [],
    }


def _physical_payload(logical, requirements=()) -> Mapping[str, object]:
    propagated_constraints = {}
    propagated_constraint_provenance = []
    for requirement in requirements:
        for key, value in requirement.payload.items():
            if str(key).startswith(("max_", "min_")):
                propagated_constraints[str(key)] = value
        for container_key in ("constraints", "limits"):
            container = requirement.payload.get(container_key)
            if isinstance(container, Mapping):
                propagated_constraints.update({str(key): value for key, value in container.items()})
        provenance = requirement.payload.get("constraint_provenance")
        if isinstance(provenance, list):
            propagated_constraint_provenance.extend(
                item for item in provenance if isinstance(item, Mapping)
            )
    return {
        "candidate_type": "可部署执行单元",
        "solution_class": "领域适配实现",
        "source_requirement_ids": sorted(item.id for item in requirements),
        "propagated_constraints": dict(sorted(propagated_constraints.items())),
        "propagated_constraint_provenance": propagated_constraint_provenance,
        "mass_kg": None,
        "power_w": None,
        "compute": "待基准测试",
        "memory_mb": None,
        "latency_ms": None,
        "bandwidth_mbps": None,
        "cost": None,
        "thermal": "待热设计评估",
        "reliability": "待可靠性试验",
        "availability": "待运行数据确认",
        "endurance_h": None,
        "swap_c": {
            "mass_kg": None,
            "power_w": None,
            "cost": None,
            "status": "requires_measurement",
        },
        "constraints": ["满足对应逻辑职责", "满足质量、功耗、时延和热约束"],
        "feasibility": {
            "status": "needs_measurement",
            "checks": ["mass", "power", "compute", "memory", "latency", "thermal"],
        },
        "alternatives": ["集中式执行单元", "分布式执行单元"],
        "trade_study": {
            "alternatives": ["集中式执行单元", "分布式执行单元"],
            "selection_rationale": f"优先承载{logical.meta.name}，在测量约束后进行候选选择",
            "decision_status": "requires_review",
        },
        "selection_rationale": f"优先承载{logical.meta.name}，在测量约束后进行候选选择",
        "rationale": f"承载{logical.meta.name}",
    }


def _physical_payload_with_reasoning(logical, requirements, linked_physical):
    payload = dict(_physical_payload(logical, requirements))
    if linked_physical is not None and "feasibility_reasoning" in linked_physical.payload:
        payload["feasibility_reasoning"] = linked_physical.payload[
            "feasibility_reasoning"
        ]
    return payload


def _record_physical_entity(builder, physical_entities, logical, physical):
    physical_entities.append(physical)
    builder.relate(logical, RelationPredicate.ALLOCATED_TO, physical)


_PHYSICAL_MEASUREMENT_FIELDS = (
    "mass_kg", "power_w", "compute", "memory_mb", "latency_ms",
    "bandwidth_mbps", "cost", "thermal", "reliability", "availability",
    "endurance_h",
)


def _set_physical_reasoning_scope(
    payload, logical, functions, requirements, physical_id, conflicts=()
):
    """Keep physical impact and re-entry choices alongside the candidate."""

    requirement_ids = [item.id for item in requirements]
    function_ids = [item.id for item in functions]
    payload.update({
        "source_logical_ids": [logical.id],
        "source_function_ids": function_ids,
        "impact_chain": {
            "requirement_ids": requirement_ids,
            "function_ids": function_ids,
            "logical_ids": [logical.id],
            "physical_ids": [physical_id],
        },
        "resolution_options": _physical_resolution_options(
            logical, functions, requirements, physical_id, conflicts
        ),
    })


def _physical_resolution_options(logical, functions, requirements, physical_id, conflicts=()):
    """Return bounded alternatives with an explicit re-entry point."""

    if not conflicts:
        return []
    requirement_ids = [item.id for item in requirements]
    impact_entity_ids = list(dict.fromkeys(
        (*requirement_ids, *(item.id for item in functions), logical.id, physical_id)
    ))
    fields = sorted({
        key for requirement in requirements
        for key in _explicit_constraint_map(requirement)
    })
    return [
        {
            "id": f"{logical.id}:physical-resolution:{index}",
            "option": option,
            "task": task,
            "reentry_stage": stage,
            "impact_entity_ids": impact_entity_ids,
            "conflict_fields": fields,
            "impact": impact,
            "requires_user_decision": True,
        }
        for index, (option, task, stage, impact) in enumerate((
            (
                "降低计算或功耗需求",
                "constraint_propagation",
                "physical",
                "可能改变功能性能或系统资源约束",
            ),
            (
                "更换物理候选或计算架构",
                "allocation_tradeoff",
                "physical",
                "保持需求，重新分配物理实现",
            ),
            (
                "调整需求约束或资源预算",
                "system_requirement_derivation",
                "requirements",
                "需要利益相关者确认后重新生成下游链路",
            ),
            (
                "增加电池质量或资源预算",
                "system_requirement_derivation",
                "requirements",
                "需要重新评估质量、续航和利益相关者约束",
            ),
        ), start=1)
    ]


def _physical_constraint_conflicts(payload, requirements):
    conflicts = []
    for requirement in requirements:
        for key, raw_limit in _explicit_constraint_map(requirement).items():
            limit = _runtime_number(raw_limit)
            value = _runtime_number(payload.get(key[4:]))
            if limit is None or value is None:
                continue
            operator = "max" if key.startswith("max_") else "min"
            violates = operator == "max" and value > limit or operator == "min" and value < limit
            if violates:
                conflicts.append({
                    "requirement_id": requirement.id,
                    "field": key[4:],
                    "operator": operator,
                    "limit": limit,
                    "value": value,
                })
    return conflicts


def _runtime_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _requirement_trace_scope(context, requirement):
    """Resolve one requirement's downstream RFLP scope for V&V planning."""

    graph = ModelGraph(
        context.project_id,
        context.entities,
        tuple(context.relations),
        context.revision,
    )
    trace = resolve_requirement_trace(graph, requirement.id)
    return {
        "function_ids": list(trace.function_ids),
        "logical_component_ids": list(trace.logical_component_ids),
        "physical_ids": list(trace.physical_ids),
    }


def _vertical_decision_records(task_id: str, context, added: dict[str, object]):
    entities = tuple(context.entities) + tuple(added.values())
    if task_id == "vertical.requirements":
        return (
            {
                "step": "operational_reasoning",
                "decision": "保留利益相关者、生命周期、场景、用例和活动上下文",
                "basis": [
                    item.id for item in entities
                    if item.kind in {
                        EntityKind.STAKEHOLDER,
                        EntityKind.LIFECYCLE_STAGE,
                        EntityKind.ACTIVITY,
                    }
                ],
            },
            {
                "step": "system_requirement_derivation",
                "decision": "从活动和运行场景推导可验证系统需求",
                "basis": [item.id for item in entities if item.kind is EntityKind.REQUIREMENT],
            },
        )
    if task_id == "vertical.functional":
        return (
            {
                "step": "function_identification",
                "decision": "从需求识别系统行为而不是具体零件",
                "basis": [item.id for item in entities if item.kind is EntityKind.REQUIREMENT],
            },
            {
                "step": "functional_interaction",
                "decision": "用功能流表达任务与结果交互",
                "basis": [item.id for item in entities if item.kind is EntityKind.FUNCTIONAL_FLOW],
            },
        )
    if task_id == "vertical.logical":
        return (
            {
                "step": "dependency_clustering",
                "decision": "按功能流、共享状态和时序依赖形成逻辑分区",
                "basis": [item.id for item in entities if item.kind is EntityKind.FUNCTION],
            },
            {
                "step": "architecture_evaluation",
                "decision": "评估内聚、耦合、时序和安全隔离后保留逻辑边界",
                "basis": [item.id for item in entities if item.kind is EntityKind.LOGICAL_COMPONENT],
            },
        )
    if task_id == "vertical.physical":
        return (
            {
                "step": "constraint_propagation",
                "decision": "将质量、功耗、算力、内存、时延和热约束传播到物理候选",
                "basis": [item.id for item in entities if item.kind is EntityKind.REQUIREMENT],
            },
            {
                "step": "feasibility_selection",
                "decision": "在测量 SWaP-C 和可行性后选择物理候选",
                "basis": [item.id for item in entities if item.kind is EntityKind.PHYSICAL_BLOCK],
            },
        )
    if task_id == "vertical.verification_validation":
        return (
            {
                "step": "verification_validation",
                "decision": "为每个需求分别建立工程验证和用户场景确认",
                "basis": [item.id for item in entities if item.kind is EntityKind.REQUIREMENT],
            },
            {
                "step": "global_cross_analysis",
                "decision": "检查需求、架构和 V&V 端到端覆盖",
                "basis": [
                    item.id for item in entities
                    if item.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
                ],
            },
        )
    return ()
