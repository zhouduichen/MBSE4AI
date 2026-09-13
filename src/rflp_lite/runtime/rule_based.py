"""Deterministic offline runtime used when no model profile is configured."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.runtime.lifecycle_rule import (
    OPERATIONAL_FUNCTIONAL_TASKS,
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
        if request.task_id in OPERATIONAL_FUNCTIONAL_TASKS:
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
        if kind is EntityKind.VERIFICATION_CASE:
            payload.update({"method": "review", "pass_criteria": "待确认的通过准则"})
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
                    {"task_id": request.task_id, "method": method, "pass_criteria": "待确认的通过准则", "requires_human_review": True},
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
        if entity.meta.status in {EntityStatus.DEPRECATED, EntityStatus.LOCKED}:
            return False
        if bool(entity.payload.get("user_modified")):
            return False
        self.operations.append(UpdateEntity(entity.id, {"payload": dict(payload)}))
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
        seed = requirements[0].meta.name if requirements else builder.context.project_id
        system = _context_first(builder.context, EntityKind.SYSTEM) or builder.add(
            EntityKind.SYSTEM, f"{seed} 系统", _system_payload(seed)
        )
        stakeholder = _context_first(builder.context, EntityKind.STAKEHOLDER) or builder.add(
            EntityKind.STAKEHOLDER, "系统使用者", {"role": "使用与验收"}
        )
        concern = _context_first(builder.context, EntityKind.CONCERN) or builder.add(
            EntityKind.CONCERN, "任务可靠性与运营可用性", {
                "topic": "在正常、异常和人工接管场景下完成可追踪任务",
                "stakeholder_ids": [stakeholder.id],
            }
        )
        scenario = _context_first(builder.context, EntityKind.OPERATIONAL_SCENARIO) or builder.add(
            EntityKind.OPERATIONAL_SCENARIO, "典型运行场景", {
                "actor_ids": [stakeholder.id],
                "steps": ["提出任务", "系统执行任务", "反馈结果"],
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
        hypothesis = _context_first(builder.context, EntityKind.SCENARIO_HYPOTHESIS) or builder.add(
            EntityKind.SCENARIO_HYPOTHESIS, "典型配送场景假设", {
                "category": "normal",
                "actors": [stakeholder.meta.name],
                "trigger": "运营人员提交配送任务",
                "outcome": "任务完成并反馈结果",
            }
        )
        use_case = _context_first(builder.context, EntityKind.USE_CASE) or builder.add(
            EntityKind.USE_CASE, "执行一次配送任务", {
                "primary_actor": stakeholder.meta.name,
                "goal": "完成可追踪配送",
                "success": "接收结果并可人工接管",
            }
        )
        activity = _context_first(builder.context, EntityKind.ACTIVITY) or builder.add(
            EntityKind.ACTIVITY, "受理并完成配送活动", {
                "steps": ["受理任务", "规划路径", "执行配送", "反馈结果"],
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
        for requirement in requirements:
            builder.relate(requirement, RelationPredicate.DERIVED_FROM, activity)
        return builder.response()

    def _functional(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        requirements = _requirements(request)
        for requirement in requirements:
            function = builder.add(EntityKind.FUNCTION, f"执行：{requirement.meta.name[:36]}", {
                "behavior": f"实现{requirement.meta.name}",
                "inputs": [],
                "outputs": ["执行结果"],
            })
            builder.relate(requirement, RelationPredicate.SATISFIED_BY, function)
        functions = _builder_entities(builder, EntityKind.FUNCTION)
        flow = builder.add(EntityKind.FUNCTIONAL_FLOW, "任务信息交互流", {
            "direction": "双向", "content": "任务与结果"
        })
        scenario = builder.add(EntityKind.FUNCTIONAL_SCENARIO, "完成核心功能场景", {
            "function_ids": [item.id for item in functions],
            "steps": ["输入", "处理", "输出"],
        })
        for function in functions:
            builder.relate(function, RelationPredicate.EXCHANGES_WITH, flow)
            builder.relate(function, RelationPredicate.DERIVED_FROM, scenario)
        return builder.response()

    def _logical(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        decision = _controller_decision(request.context_bundle)
        option = str(decision.get("option", "")).strip()
        variant = option if option in _LOGICAL_VARIANTS else ""
        functions = _context_entities(request.context_bundle, EntityKind.FUNCTION)
        groups = _partition_functions(functions)
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
            if variant == "one_component_per_function":
                groups = tuple((function,) for function in functions)
            elif variant == "shared_coordinator" and functions:
                groups = (tuple(functions),)
            blocked = False
            for item in request.context_bundle.entities:
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
        else:
            blocked = False
        logical_components = []
        for group in groups:
            label = _partition_label(group)
            base_name = (
                "配送协同逻辑架构"
                if len(groups) == 1 and len(group) == 1
                else f"{group[0].meta.name}逻辑组件"
                if variant == "one_component_per_function" and len(group) == 1
                else f"{label}逻辑组件"
            )
            name = f"{base_name}（{variant}）" if variant else base_name
            shared_state = _union_payload_values(group, "shared_state") or ["配送任务状态"]
            timing_constraints = _union_payload_values(group, "timing_constraints") or ["任务状态更新必须可排序"]
            payload = {
                "responsibility": "；".join(
                    str(item.payload.get("behavior") or item.meta.name)
                    for item in group
                ),
                "partition_basis": (
                    f"按 {label} 的功能职责形成独立分区"
                    if len(group) == 1
                    else f"按 {label} 共享状态和功能依赖形成分区"
                ),
                "dependencies": [item.id for item in group],
                "shared_state": shared_state,
                "timing_constraints": timing_constraints,
                "safety_isolation": ["人工接管路径与自动执行路径隔离"],
                "cohesion": "high",
                "coupling": "controlled" if len(group) == 1 else "high",
                "interfaces": [],
                "architecture_rationale": (
                    "单一功能职责保持边界清晰"
                    if len(group) == 1
                    else "共享状态使功能保持在同一逻辑边界，但需要评审耦合"
                ),
            }
            if variant:
                payload.update({
                    "architecture_variant": variant,
                    "architecture_decision": dict(_decision_payload(decision)),
                })
                if blocked:
                    payload["blocked_by_locked_entity"] = True
            logical_components.append(builder.add(EntityKind.LOGICAL_COMPONENT, name, payload))
        if not logical_components:
            return builder.response()
        suffix = f"（{variant}）" if variant else ""
        state = builder.add(EntityKind.STATE, f"配送任务状态{suffix}", {
            "values": ["待受理", "执行中", "人工接管", "完成", "失败"],
            "transitions": [
                "待受理->执行中", "执行中->人工接管", "执行中->完成",
                "执行中->失败", "失败->执行中",
            ],
            "owner_id": logical_components[0].id,
            "owner_ids": [item.id for item in logical_components],
        })
        interface = builder.add(EntityKind.INTERFACE, f"配送任务交互接口{suffix}", {
            "protocol": "logical-message",
            "exchanges": ["task_request", "task_status", "handover"],
            "connected_component_ids": [item.id for item in logical_components],
        })
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
        decision = _controller_decision(request.context_bundle)
        option = str(decision.get("option", "")).strip()
        physical_variant = option if option in _PHYSICAL_VARIANTS else ""
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
            name = (
                "配送协同执行平台"
                if len(logical_components) == 1
                else f"{logical.meta.name}执行平台"
            )
            payload = dict(_physical_payload(logical, requirements))
            if physical_variant == "更换物理候选或计算架构":
                name = f"{name}替代候选"
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
                physical = builder.add(EntityKind.PHYSICAL_BLOCK, name, payload)
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
            builder.relate(logical, RelationPredicate.ALLOCATED_TO, physical)
            for requirement in requirements:
                constraints = _explicit_constraint_map(requirement)
                if not constraints:
                    continue
                technical = builder.add(
                    EntityKind.REQUIREMENT,
                    f"{physical.meta.name}技术约束：{requirement.meta.name[:24]}",
                    _technical_requirement_payload(requirement, physical, constraints),
                )
                builder.relate(technical, RelationPredicate.DERIVED_FROM, requirement)
                builder.relate(technical, RelationPredicate.SATISFIED_BY, physical)
        return builder.response()

    def _verification_validation(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        builder = _VerticalPatchBuilder(request)
        activities = _context_entities(request.context_bundle, EntityKind.ACTIVITY)
        branch_names = [
            branch
            for activity in activities
            for branch in activity.payload.get("branches", ())
            if str(branch).strip()
        ]
        activity_ids = [item.id for item in activities]
        for requirement in _requirements(request):
            verification = builder.add(EntityKind.VERIFICATION_CASE, f"验证：{requirement.meta.name[:32]}", {
                "method": "test",
                "precondition": "系统处于可测试初始状态",
                "input": requirement.meta.name,
                "procedure": "执行测试步骤并记录实际结果",
                "expected_result": "实际结果满足需求目标",
                    "pass_criteria": f"测试结果满足：{requirement.meta.name}",
                    "evidence_ids": [],
                    "requirement_ids": [requirement.id],
                    "scenario_ids": [],
                    "activity_ids": activity_ids,
                    "covered_branches": branch_names,
                })
            validation = builder.add(EntityKind.VALIDATION_CASE, f"确认：{requirement.meta.name[:32]}", {
                "method": "demonstration",
                "precondition": "目标用户和典型场景可用",
                "input": requirement.meta.name,
                "procedure": "在典型场景执行并收集用户反馈",
                "expected_result": "用户场景目标达成",
                    "pass_criteria": f"用户场景确认：{requirement.meta.name}",
                    "evidence_ids": [],
                    "requirement_ids": [requirement.id],
                    "scenario_ids": [],
                    "activity_ids": activity_ids,
                    "covered_branches": branch_names,
                })
            hazard = builder.add(EntityKind.HAZARD, f"风险：{requirement.meta.name[:28]}", {
                "description": "异常分支、资源异常或人工接管不当导致任务目标未达成",
                "requirement_ids": [requirement.id],
                "activity_ids": activity_ids,
                "branches": branch_names,
            })
            failure_mode = builder.add(EntityKind.FAILURE_MODE, f"失效模式：{requirement.meta.name[:28]}", {
                "effect": "需求未满足或任务结果不可追踪",
                "cause": "执行条件、资源或交互异常",
                "requirement_ids": [requirement.id],
                "activity_ids": activity_ids,
            })
            builder.relate(requirement, RelationPredicate.VERIFIED_BY, verification)
            builder.relate(requirement, RelationPredicate.VALIDATED_BY, validation)
            builder.relate(hazard, RelationPredicate.DERIVED_FROM, requirement)
            builder.relate(hazard, RelationPredicate.CAUSES, failure_mode)
            builder.relate(hazard, RelationPredicate.MITIGATED_BY, verification)
            builder.relate(failure_mode, RelationPredicate.MITIGATED_BY, verification)
        return builder.response()


def _partition_functions(functions):
    groups = {}
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
        groups.setdefault(key, []).append(function)
    return tuple(tuple(group) for group in groups.values())


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
        "selection_rationale": f"优先承载{logical.meta.name}，在测量约束后进行候选选择",
        "rationale": f"承载{logical.meta.name}",
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
