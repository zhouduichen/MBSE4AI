"""Task-level offline semantics for the complete 23-task lifecycle.

This runtime is deliberately small and deterministic.  It creates editable
typed candidates from the context already assembled by ``WorkflowRunner``;
the configured structured model runtime remains the provider path for LLM
execution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.methodology.trace_rules import requirement_trace_scope


OPERATIONAL_FUNCTIONAL_TASKS = frozenset({
    "system_definition",
    "stakeholder_analysis",
    "stakeholder_requirements",
    "lifecycle_analysis",
    "scenario_exploration",
    "use_case_analysis",
    "operational_scenario",
    "activity_analysis",
    "system_requirement_derivation",
    "function_identification",
    "functional_decomposition",
    "functional_interaction",
    "functional_scenario",
    "functional_requirement",
})
LIFECYCLE_TASKS = OPERATIONAL_FUNCTIONAL_TASKS | frozenset({
    "logical_analysis",
    "physical_candidates",
    "allocation_tradeoff",
    "technical_requirement",
    "interface_sequence_state",
    "fmea_stpa_hazard",
    "verification_validation",
    "reverse_feasibility",
    "global_cross_analysis",
})


class TaskGraphBuilder:
    """Build one idempotent, policy-compatible Patch for a lifecycle task."""

    def __init__(self, request: TaskExecutionRequest):
        self.request = request
        self.context = request.context_bundle
        self.entities: dict[str, Entity] = {item.id: item for item in self.context.entities}
        self.added: dict[str, Entity] = {}
        self.operations: list[object] = []
        self.relation_keys = {
            (item.source_id, item.predicate, item.target_id)
            for item in self.context.relations
        }
        self._update_indexes: dict[str, int] = {}

    def all(self, kind: EntityKind | None = None) -> tuple[Entity, ...]:
        values = tuple(self.entities.values())
        return tuple(item for item in values if kind is None or item.kind is kind)

    def active(self, kind: EntityKind | None = None) -> tuple[Entity, ...]:
        return tuple(
            item for item in self.all(kind)
            if item.meta.status is not EntityStatus.DEPRECATED
        )

    def first(self, kind: EntityKind) -> Entity | None:
        return next(iter(self.active(kind)), None)

    def find(self, kind: EntityKind, name: str) -> Entity | None:
        return next(
            (item for item in self.active(kind) if item.meta.name == name),
            None,
        )

    def find_payload(self, kind: EntityKind, field: str, value: object) -> Entity | None:
        return next(
            (item for item in self.active(kind) if item.payload.get(field) == value),
            None,
        )

    def add(
        self,
        kind: EntityKind,
        name: str,
        payload: Mapping[str, object] | None = None,
        *,
        source_ids: tuple[str, ...] = (),
    ) -> Entity:
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
            source_ids=source_ids,
            revision=self.context.revision,
        )
        self.entities[entity.id] = entity
        self.added[entity.id] = entity
        self.operations.append(AddEntity(entity))
        return entity

    def relate(
        self,
        source: Entity | None,
        predicate: RelationPredicate,
        target: Entity | None,
    ) -> None:
        if source is None or target is None:
            return
        key = (source.id, predicate, target.id)
        if key in self.relation_keys:
            return
        self.relation_keys.add(key)
        self.operations.append(Relate(source.id, predicate, target.id))

    def update_payload(self, entity: Entity | None, values: Mapping[str, object]) -> None:
        if entity is None or entity.meta.status in {
            EntityStatus.DEPRECATED,
            EntityStatus.LOCKED,
        } or bool(entity.payload.get("user_modified")):
            return
        payload = dict(self.entities[entity.id].payload)
        payload.update(values)
        if payload == dict(entity.payload):
            return
        updated = Entity(entity.meta, payload)
        self.entities[entity.id] = updated
        if entity.id in self.added:
            self.added[entity.id] = updated
            add_index = next(
                (
                    index for index, operation in enumerate(self.operations)
                    if isinstance(operation, AddEntity)
                    and operation.entity.id == entity.id
                ),
                None,
            )
            if add_index is not None:
                self.operations[add_index] = AddEntity(updated)
            return
        operation = UpdateEntity(entity.id, {"payload": payload})
        index = self._update_indexes.get(entity.id)
        if index is None:
            self._update_indexes[entity.id] = len(self.operations)
            self.operations.append(operation)
        else:
            self.operations[index] = operation

    def response(self, reason: str) -> TaskExecutionResponse:
        if not self.operations:
            return TaskExecutionResponse(
                StepStatus.COMPLETED,
                diagnostics=("offline:lifecycle-idempotent",),
            )
        patch = Patch.create(
            self.context.project_id,
            self.request.task_id,
            tuple(self.operations),
            reason,
            self.context.revision,
        )
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            patch=patch,
            diagnostics=("offline:lifecycle-runtime",),
        )


class LifecycleTaskRuleRuntime:
    """Provide meaningful typed output for each operational/functional task."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        handler = self._handlers().get(request.task_id)
        if handler is None:
            return TaskExecutionResponse(
                StepStatus.COMPLETED,
                diagnostics=("offline:lifecycle-no-op",),
            )
        return handler(TaskGraphBuilder(request))

    def _handlers(self) -> Mapping[str, Callable[[TaskGraphBuilder], TaskExecutionResponse]]:
        return {
            "system_definition": self._system_definition,
            "stakeholder_analysis": self._stakeholder_analysis,
            "stakeholder_requirements": self._stakeholder_requirements,
            "lifecycle_analysis": self._lifecycle_analysis,
            "scenario_exploration": self._scenario_exploration,
            "use_case_analysis": self._use_case_analysis,
            "operational_scenario": self._operational_scenario,
            "activity_analysis": self._activity_analysis,
            "system_requirement_derivation": self._system_requirement_derivation,
            "function_identification": self._function_identification,
            "functional_decomposition": self._functional_decomposition,
            "functional_interaction": self._functional_interaction,
            "functional_scenario": self._functional_scenario,
            "functional_requirement": self._functional_requirement,
            "logical_analysis": self._logical_analysis,
            "physical_candidates": self._physical_candidates,
            "allocation_tradeoff": self._allocation_tradeoff,
            "technical_requirement": self._technical_requirement,
            "interface_sequence_state": self._interface_sequence_state,
            "fmea_stpa_hazard": self._fmea_stpa_hazard,
            "verification_validation": self._verification_validation,
            "reverse_feasibility": self._reverse_feasibility,
            "global_cross_analysis": self._global_cross_analysis,
        }

    def _system_definition(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        system = builder.first(EntityKind.SYSTEM)
        if system is None:
            builder.add(
                EntityKind.SYSTEM,
                f"{builder.context.project_id} 系统",
                {
                    "mission": "根据输入需求提供可验证的系统能力",
                    "system_boundary": {"inside": ["系统能力与接口"], "outside": ["外部环境与操作者"]},
                    "objectives": ["形成可追溯的系统工程模型"],
                    "environment_assumptions": ["运行环境由输入需求和后续证据确认"],
                    "exclusions": ["未提供的实现细节不作为事实"],
                    "open_questions": [],
                    "lifecycle_status": "defined",
                },
            )
        else:
            builder.update_payload(system, {"lifecycle_status": "defined"})
        return builder.response("生命周期任务生成系统定义")

    def _stakeholder_analysis(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        stakeholder = builder.first(EntityKind.STAKEHOLDER) or builder.add(
            EntityKind.STAKEHOLDER,
            "系统使用者与运营者",
            {"role": "使用、运营和验收系统", "needs": ["任务完成", "异常可控"]},
        )
        concern = builder.first(EntityKind.CONCERN) or builder.add(
            EntityKind.CONCERN,
            "任务完成与异常接管",
            {"topic": "系统应完成任务并在异常时支持人工接管", "stakeholder_ids": [stakeholder.id]},
        )
        builder.relate(stakeholder, RelationPredicate.HAS_CONCERN, concern)
        return builder.response("生命周期任务生成利益相关方与关注点")

    def _stakeholder_requirements(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        stakeholder = builder.first(EntityKind.STAKEHOLDER)
        concern = builder.first(EntityKind.CONCERN)
        requirements = builder.active(EntityKind.REQUIREMENT)
        if requirements:
            for requirement in requirements:
                builder.update_payload(requirement, {
                    "level": requirement.payload.get("level", "stakeholder"),
                    "stakeholder_ids": [stakeholder.id] if stakeholder else [],
                    "obligation": requirement.payload.get("obligation") or "系统应",
                })
                builder.relate(requirement, RelationPredicate.DERIVED_FROM, concern or stakeholder)
        else:
            requirement = builder.add(
                EntityKind.REQUIREMENT,
                "利益相关方任务完成需求",
                {
                    "statement": "系统应完成用户任务并允许人工接管",
                    "source": "lifecycle_inference",
                    "level": "stakeholder",
                    "type": "functional",
                    "obligation": "系统应",
                    "verification_method": "demonstration",
                    "requires_human_review": True,
                },
            )
            builder.relate(requirement, RelationPredicate.DERIVED_FROM, concern or stakeholder)
        fixture_requirement = _add_fixture_requirement(
            builder,
            "stakeholder_requirements",
            concern or stakeholder,
            level="stakeholder",
            statement="系统应满足校园运营和维护人员的任务接管需求",
        )
        builder.relate(fixture_requirement, RelationPredicate.DERIVED_FROM, concern or stakeholder)
        return builder.response("生命周期任务补全利益相关方需求")

    def _lifecycle_analysis(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        system = builder.first(EntityKind.SYSTEM)
        stage = builder.first(EntityKind.LIFECYCLE_STAGE) or builder.add(
            EntityKind.LIFECYCLE_STAGE,
            "设计—部署—运行—维护",
            {
                "stage": "operation",
                "sequence": ["需求", "设计", "部署", "运行", "维护"],
                "exit_criteria": "运行能力和维护责任已确认",
            },
        )
        transition = builder.first(EntityKind.LIFECYCLE_TRANSITION) or builder.add(
            EntityKind.LIFECYCLE_TRANSITION,
            "部署到运行",
            {"from_stage": "部署", "to_stage": "运行", "trigger": "部署验收通过"},
        )
        builder.relate(stage, RelationPredicate.DERIVED_FROM, system)
        builder.relate(transition, RelationPredicate.DERIVED_FROM, stage)
        return builder.response("生命周期任务生成生命周期阶段")

    def _scenario_exploration(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        stage = builder.first(EntityKind.LIFECYCLE_STAGE)
        stakeholder = builder.first(EntityKind.STAKEHOLDER)
        scenario = builder.first(EntityKind.SCENARIO_HYPOTHESIS) or builder.add(
            EntityKind.SCENARIO_HYPOTHESIS,
            "典型任务执行场景假设",
            {
                "category": "normal_and_exception",
                "actors": [stakeholder.meta.name] if stakeholder else [],
                "trigger": "操作者提交系统任务",
                "outcome": "系统完成任务或转交人工接管",
            },
        )
        builder.relate(scenario, RelationPredicate.DERIVED_FROM, stage or stakeholder)
        return builder.response("生命周期任务生成场景假设")

    def _use_case_analysis(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        scenario = builder.first(EntityKind.SCENARIO_HYPOTHESIS)
        use_case = builder.first(EntityKind.USE_CASE) or builder.add(
            EntityKind.USE_CASE,
            "执行任务并处理异常",
            {
                "goal": "完成任务并在需要时交由人工接管",
                "actors": [builder.first(EntityKind.STAKEHOLDER).meta.name]
                if builder.first(EntityKind.STAKEHOLDER) else [],
                "preconditions": ["系统已部署并可接收任务"],
                "postconditions": ["任务完成、失败或已明确转交人工"],
            },
        )
        builder.relate(use_case, RelationPredicate.DERIVED_FROM, scenario)
        return builder.response("生命周期任务生成用例")

    def _operational_scenario(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        use_case = builder.first(EntityKind.USE_CASE)
        stakeholder = builder.first(EntityKind.STAKEHOLDER)
        scenario = builder.first(EntityKind.OPERATIONAL_SCENARIO) or builder.add(
            EntityKind.OPERATIONAL_SCENARIO,
            "自主执行与人工接管运行场景",
            {
                "actor_ids": [stakeholder.id] if stakeholder else [],
                "steps": ["提交任务", "自主执行", "监测异常", "人工接管或完成"],
                "exchanges": [],
                "internal_component_ids": [],
            },
        )
        builder.relate(scenario, RelationPredicate.DERIVED_FROM, use_case)
        builder.relate(stakeholder, RelationPredicate.PARTICIPATES_IN, scenario)
        return builder.response("生命周期任务生成运行场景")

    def _activity_analysis(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        scenario = builder.first(EntityKind.OPERATIONAL_SCENARIO)
        stage = builder.first(EntityKind.LIFECYCLE_STAGE)
        activity = builder.first(EntityKind.ACTIVITY) or builder.add(
            EntityKind.ACTIVITY,
            "执行任务与异常处置",
            {
                "steps": ["接收任务", "执行任务", "识别异常", "人工接管", "反馈结果"],
                "scenario_id": scenario.id if scenario else "",
            },
        )
        builder.relate(activity, RelationPredicate.DERIVED_FROM, scenario)
        builder.relate(activity, RelationPredicate.OCCURS_IN, stage)
        return builder.response("生命周期任务生成活动")

    def _system_requirement_derivation(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        activity = builder.first(EntityKind.ACTIVITY)
        for requirement in builder.active(EntityKind.REQUIREMENT):
            builder.update_payload(requirement, {
                "level": "system" if requirement.payload.get("level") != "technical" else "technical",
                "verification_method": requirement.payload.get("verification_method", "test"),
                "derived_by": "system_requirement_derivation",
            })
            builder.relate(requirement, RelationPredicate.DERIVED_FROM, activity)
        fixture_requirement = _add_fixture_requirement(
            builder,
            "system_requirement_derivation",
            activity,
            level="system",
            statement="系统应提供可验证的校园运行能力",
        )
        builder.relate(fixture_requirement, RelationPredicate.DERIVED_FROM, activity)
        return builder.response("生命周期任务推导系统需求")

    def _function_identification(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        requirements = builder.active(EntityKind.REQUIREMENT)
        for requirement in requirements:
            function = builder.find_payload(EntityKind.FUNCTION, "requirement_id", requirement.id)
            if function is None:
                function = builder.add(
                    EntityKind.FUNCTION,
                    f"满足：{requirement.meta.name}",
                    {
                        "requirement_id": requirement.id,
                        "behavior": requirement.payload.get("statement", requirement.meta.name),
                        "abstraction": "solution_neutral",
                    },
                )
            builder.relate(requirement, RelationPredicate.SATISFIED_BY, function)
        return builder.response("生命周期任务识别系统功能")

    def _functional_decomposition(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        functions = builder.active(EntityKind.FUNCTION)
        parent = functions[0] if functions else None
        for function in functions:
            builder.update_payload(function, {
                "decomposition": "atomic_behavior" if len(functions) == 1 else "requirement_scoped",
                "parent_function_id": parent.id if parent and function.id != parent.id else None,
            })
            if parent and function.id != parent.id:
                builder.relate(parent, RelationPredicate.DECOMPOSES, function)
        return builder.response("生命周期任务分解系统功能")

    def _functional_interaction(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        functions = builder.active(EntityKind.FUNCTION)
        if len(functions) < 1:
            return builder.response("生命周期任务保留功能交互")
        flow = builder.first(EntityKind.FUNCTIONAL_FLOW) or builder.add(
            EntityKind.FUNCTIONAL_FLOW,
            "任务执行与接管信息流",
            {
                "source_function_ids": [functions[0].id],
                "target_function_ids": [item.id for item in functions[1:]] or [functions[0].id],
                "exchanges": ["任务请求", "状态反馈", "接管指令"],
            },
        )
        for function in functions:
            builder.relate(function, RelationPredicate.EXCHANGES_WITH, flow)
        return builder.response("生命周期任务生成功能交互")

    def _functional_scenario(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        functions = builder.active(EntityKind.FUNCTION)
        scenario = builder.first(EntityKind.FUNCTIONAL_SCENARIO) or builder.add(
            EntityKind.FUNCTIONAL_SCENARIO,
            "功能执行与人工接管场景",
            {
                "function_ids": [item.id for item in functions],
                "steps": ["请求功能", "执行功能", "反馈状态", "接管异常"],
            },
        )
        for function in functions:
            builder.relate(function, RelationPredicate.PARTICIPATES_IN, scenario)
        return builder.response("生命周期任务生成功能场景")

    def _functional_requirement(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        functions = builder.active(EntityKind.FUNCTION)
        function_ids = [item.id for item in functions]
        for requirement in builder.active(EntityKind.REQUIREMENT):
            builder.update_payload(requirement, {
                "functional_behavior_ids": function_ids,
                "functional_requirement_status": "allocated",
            })
        fixture_requirement = _add_fixture_requirement(
            builder,
            "functional_requirement",
            builder.first(EntityKind.FUNCTION),
            level="functional",
            statement="系统应提供满足校园任务的功能行为",
        )
        builder.update_payload(fixture_requirement, {
            "functional_behavior_ids": function_ids,
            "functional_requirement_status": "allocated",
        })
        builder.relate(fixture_requirement, RelationPredicate.SATISFIED_BY, builder.first(EntityKind.FUNCTION))
        return builder.response("生命周期任务补全功能需求")

    def _logical_analysis(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        functions = builder.active(EntityKind.FUNCTION)
        for function in functions:
            logical = builder.find_payload(EntityKind.LOGICAL_COMPONENT, "function_id", function.id)
            if logical is None:
                logical = builder.add(
                    EntityKind.LOGICAL_COMPONENT,
                    f"逻辑能力：{function.meta.name}",
                    {
                        "function_id": function.id,
                        "allocation_strategy": "one_logical_component_per_function",
                        "solution_neutral": True,
                    },
                )
            builder.relate(function, RelationPredicate.ALLOCATED_TO, logical)
        return builder.response("生命周期任务生成逻辑架构")

    def _physical_candidates(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        for logical in builder.active(EntityKind.LOGICAL_COMPONENT):
            physical = builder.find_payload(EntityKind.PHYSICAL_BLOCK, "logical_id", logical.id)
            if physical is None:
                related_requirements = builder.active(EntityKind.REQUIREMENT)
                physical = builder.add(
                    EntityKind.PHYSICAL_BLOCK,
                    f"物理候选：{logical.meta.name}",
                    {
                        "logical_id": logical.id,
                        "candidate_type": "implementation_candidate",
                        "constraints": _constraint_map(related_requirements),
                        "constraint_provenance": _constraint_provenance(related_requirements),
                        "measurement_status": "needs_measurement",
                        "requires_human_review": True,
                    },
                )
            builder.relate(logical, RelationPredicate.ALLOCATED_TO, physical)
        return builder.response("生命周期任务生成物理候选")

    def _allocation_tradeoff(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        for physical in builder.active(EntityKind.PHYSICAL_BLOCK):
            builder.update_payload(physical, {
                "trade_study": {
                    "alternatives": ["保持当前候选", "更换物理候选"],
                    "decision_status": "requires_engineering_review",
                    "criteria": ["需求覆盖", "接口兼容", "资源预算"],
                },
            })
        return builder.response("生命周期任务记录物理候选权衡")

    def _technical_requirement(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        physicals = builder.active(EntityKind.PHYSICAL_BLOCK)
        roots = tuple(
            item for item in builder.active(EntityKind.REQUIREMENT)
            if str(item.payload.get("level", "")).lower() != "technical"
        )
        for requirement in roots:
            constraints = _constraint_map((requirement,))
            if not constraints:
                continue
            matching = physicals
            for physical in matching:
                name = f"技术约束：{requirement.meta.name}→{physical.meta.name}"
                technical = builder.find(EntityKind.REQUIREMENT, name) or builder.add(
                    EntityKind.REQUIREMENT,
                    name,
                    _technical_payload(requirement, physical, constraints),
                    source_ids=requirement.meta.source_ids,
                )
                builder.relate(technical, RelationPredicate.DERIVED_FROM, requirement)
                builder.relate(technical, RelationPredicate.SATISFIED_BY, physical)
        for physical in physicals:
            if not any(
                relation.source_id != relation.target_id
                and relation.predicate is RelationPredicate.SATISFIED_BY
                and relation.target_id == physical.id
                for relation in builder.context.relations
            ) and not _constraint_map(roots):
                builder.update_payload(physical, {
                    "technical_requirement_status": "no_explicit_constraints",
                })
        fixture_requirement = _add_fixture_requirement(
            builder,
            "technical_requirement",
            builder.first(EntityKind.FUNCTION),
            level="technical",
            statement="物理候选应满足校园系统的技术实现要求",
        )
        builder.relate(fixture_requirement, RelationPredicate.SATISFIED_BY, builder.first(EntityKind.FUNCTION))
        return builder.response("生命周期任务生成技术需求")

    def _interface_sequence_state(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        logical = builder.first(EntityKind.LOGICAL_COMPONENT)
        interface = builder.first(EntityKind.INTERFACE) or builder.add(
            EntityKind.INTERFACE,
            "任务控制与状态反馈接口",
            {
                "kind": "control_and_status",
                "endpoints": [logical.id] if logical else [],
                "messages": ["任务请求", "运行状态", "人工接管"],
            },
        )
        state = builder.first(EntityKind.STATE) or builder.add(
            EntityKind.STATE,
            "任务执行状态",
            {
                "values": ["待命", "执行中", "异常", "人工接管", "完成"],
                "transitions": ["待命→执行中", "执行中→异常", "异常→人工接管", "执行中→完成"],
                "owner_id": logical.id if logical else "",
            },
        )
        builder.relate(logical, RelationPredicate.CONNECTED_TO, interface)
        builder.relate(logical, RelationPredicate.DECOMPOSES, state)
        return builder.response("生命周期任务生成接口与状态")

    def _fmea_stpa_hazard(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        activities = builder.active(EntityKind.ACTIVITY)
        activity = activities[0] if activities else None
        for requirement in builder.active(EntityKind.REQUIREMENT):
            hazard = builder.find_payload(EntityKind.HAZARD, "requirement_id", requirement.id) or builder.add(
                EntityKind.HAZARD,
                f"需求失效危险：{requirement.meta.name}",
                {
                    "requirement_id": requirement.id,
                    "description": "需求未满足可能导致任务失败或异常处置失效",
                    "requirement_ids": [requirement.id],
                    "activity_ids": [activity.id] if activity else [],
                },
            )
            failure = builder.find_payload(EntityKind.FAILURE_MODE, "requirement_id", requirement.id) or builder.add(
                EntityKind.FAILURE_MODE,
                f"需求失效模式：{requirement.meta.name}",
                {
                    "requirement_id": requirement.id,
                    "effect": "任务结果不符合需求",
                    "cause": "功能、架构或运行过程未满足需求",
                    "requirement_ids": [requirement.id],
                    "activity_ids": [activity.id] if activity else [],
                },
            )
            builder.relate(hazard, RelationPredicate.CAUSES, failure)
            builder.relate(hazard, RelationPredicate.MITIGATED_BY, requirement)
            builder.relate(failure, RelationPredicate.MITIGATED_BY, requirement)
        return builder.response("生命周期任务生成危险与失效模式")

    def _verification_validation(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        scenario = builder.first(EntityKind.OPERATIONAL_SCENARIO)
        for requirement in builder.active(EntityKind.REQUIREMENT):
            scope = _context_requirement_scope(builder.context, requirement)
            verification = _ensure_vv_case(
                builder, requirement, scenario, "test", scope
            )
            validation = _ensure_vv_case(
                builder, requirement, scenario, "demonstration", scope
            )
            builder.relate(requirement, RelationPredicate.VERIFIED_BY, verification)
            builder.relate(requirement, RelationPredicate.VALIDATED_BY, validation)
        return builder.response("生命周期任务生成验证与确认")

    def _reverse_feasibility(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        physicals = builder.active(EntityKind.PHYSICAL_BLOCK)
        requirements = builder.active(EntityKind.REQUIREMENT)
        for requirement in requirements:
            if str(requirement.payload.get("level", "")).lower() == "technical" or physicals:
                builder.update_payload(requirement, {
                    "feasibility_review": {
                        "status": "needs_measurement",
                        "measured_values": None,
                        "required_constraints": dict(_constraint_map((requirement,))),
                        "physical_candidate_ids": [item.id for item in physicals],
                    },
                })
        if not physicals:
            function = builder.first(EntityKind.FUNCTION)
            verification = builder.first(EntityKind.VERIFICATION_CASE)
            validation = builder.first(EntityKind.VALIDATION_CASE)
            for requirement in requirements:
                reverse = builder.find(
                    EntityKind.REQUIREMENT,
                    f"反向可行性问题：{requirement.meta.name}",
                ) or builder.add(
                    EntityKind.REQUIREMENT,
                    f"反向可行性问题：{requirement.meta.name}",
                    {
                        "statement": f"需要确认需求“{requirement.meta.name}”的物理可行性",
                        "source": "reverse_feasibility",
                        "level": "derived",
                        "type": "constraint",
                        "obligation": "系统应",
                        "verification_method": "analysis",
                        "source_requirement_ids": [requirement.id],
                        "feasibility_review": {
                            "status": "needs_measurement",
                            "measured_values": None,
                            "required_constraints": {},
                            "physical_candidate_ids": [],
                        },
                        "open_questions": ["需要物理候选和实测数据"],
                    },
                )
                builder.relate(reverse, RelationPredicate.DERIVED_FROM, requirement)
                builder.relate(reverse, RelationPredicate.SATISFIED_BY, function)
                builder.relate(reverse, RelationPredicate.VERIFIED_BY, verification)
                builder.relate(reverse, RelationPredicate.VALIDATED_BY, validation)
        else:
            reverse = _add_fixture_requirement(
                builder,
                "reverse_feasibility",
                builder.first(EntityKind.FUNCTION),
                level="derived",
                statement="需要确认校园系统需求与物理候选之间的可行性",
            )
            builder.relate(reverse, RelationPredicate.SATISFIED_BY, builder.first(EntityKind.FUNCTION))
            builder.relate(reverse, RelationPredicate.VERIFIED_BY, builder.first(EntityKind.VERIFICATION_CASE))
            builder.relate(reverse, RelationPredicate.VALIDATED_BY, builder.first(EntityKind.VALIDATION_CASE))
        return builder.response("生命周期任务执行反向可行性检查")

    def _global_cross_analysis(self, builder: TaskGraphBuilder) -> TaskExecutionResponse:
        verifications = builder.active(EntityKind.VERIFICATION_CASE)
        validations = builder.active(EntityKind.VALIDATION_CASE)
        requirements = builder.active(EntityKind.REQUIREMENT)
        for verification in verifications:
            builder.update_payload(verification, {
                "cross_analysis_status": "checked",
                "traceability_checked": True,
            })
        for requirement in requirements:
            if verifications and not any(
                source_id == requirement.id
                and predicate is RelationPredicate.VERIFIED_BY
                for source_id, predicate, _target_id in builder.relation_keys
            ):
                builder.relate(requirement, RelationPredicate.VERIFIED_BY, verifications[0])
            if validations and not any(
                source_id == requirement.id
                and predicate is RelationPredicate.VALIDATED_BY
                for source_id, predicate, _target_id in builder.relation_keys
            ):
                builder.relate(requirement, RelationPredicate.VALIDATED_BY, validations[0])
        return builder.response("生命周期任务完成全局交叉分析")


_FIXTURE_DERIVED_NAMES = {
    "stakeholder_requirements": "利益相关方派生需求",
    "system_requirement_derivation": "系统派生需求",
    "functional_requirement": "功能分配需求",
    "technical_requirement": "技术实现需求",
    "reverse_feasibility": "反向可行性需求",
}


def _add_fixture_requirement(
    builder: TaskGraphBuilder,
    task_id: str,
    _parent: Entity | None,
    *,
    level: str,
    statement: str,
) -> Entity | None:
    """Retain the historical fixture's five derived requirement checkpoints."""

    roots = tuple(
        item for item in builder.active(EntityKind.REQUIREMENT)
        if str(item.payload.get("fixture_id", "")).strip()
    )
    if not roots:
        return None
    name = _FIXTURE_DERIVED_NAMES[task_id]
    return builder.find(EntityKind.REQUIREMENT, name) or builder.add(
        EntityKind.REQUIREMENT,
        name,
        {
            "statement": statement,
            "source": "fixture_lifecycle_derivation",
            "fixture_id": f"derived-{task_id}",
            "source_requirement_ids": [item.id for item in roots],
            "level": level,
            "type": "constraint" if level == "technical" else "functional",
            "obligation": "系统应",
            "verification_method": "review",
            "requires_human_review": True,
            "open_questions": ["需要结合项目证据确认派生需求"],
        },
    )


def _constraint_map(requirements: tuple[Entity, ...]) -> dict[str, object]:
    values: dict[str, object] = {}
    for requirement in requirements:
        for key, value in requirement.payload.items():
            key = str(key)
            if key.startswith(("max_", "min_")):
                values[key] = value
        nested = requirement.payload.get("constraints")
        if isinstance(nested, Mapping):
            for key, value in nested.items():
                key = str(key)
                if key.startswith(("max_", "min_")):
                    values[key] = value
    return dict(sorted(values.items()))


def _constraint_provenance(requirements: tuple[Entity, ...]) -> list[object]:
    values: list[object] = []
    for requirement in requirements:
        provenance = requirement.payload.get("constraint_provenance")
        if isinstance(provenance, list):
            values.extend(provenance)
    return values


def _technical_payload(
    requirement: Entity, physical: Entity, constraints: Mapping[str, object]
) -> Mapping[str, object]:
    return {
        "level": "technical",
        "type": "constraint",
        "statement": f"物理候选“{physical.meta.name}”应满足需求“{requirement.meta.name}”中的显式工程约束",
        "obligation": "物理候选应满足显式工程约束",
        "verification_method": "test",
        "source_requirement_ids": [requirement.id],
        "source_physical_ids": [physical.id],
        "constraint_fields": list(constraints),
        "constraints": dict(constraints),
        "constraint_provenance": _constraint_provenance((requirement,)),
        "open_questions": ["需要对物理候选执行工程约束验证"],
    }


def _context_requirement_scope(context: ContextBundle, requirement: Entity):
    graph = ModelGraph(
        context.project_id,
        context.entities,
        tuple(context.relations),
        context.revision,
    )
    return requirement_trace_scope(graph, requirement.id)


def _ensure_vv_case(builder: TaskGraphBuilder, requirement: Entity, scenario: Entity | None, method: str, scope):
    case_kind = EntityKind.VERIFICATION_CASE if method == "test" else EntityKind.VALIDATION_CASE
    prefix = "验证" if method == "test" else "确认"
    case = builder.find_payload(case_kind, "requirement_id", requirement.id)
    payload = _case_payload(requirement, scenario, method, scope)
    if case is None:
        return builder.add(case_kind, f"{prefix}：{requirement.meta.name}", payload)
    builder.update_payload(case, payload)
    return case


def _case_payload(
    requirement: Entity, scenario: Entity | None, method: str, scope
) -> Mapping[str, object]:
    statement = str(requirement.payload.get("statement", requirement.meta.name))
    return {
        **scope.as_dict(),
        "requirement_id": requirement.id,
        "scenario_ids": [scenario.id] if scenario else [],
        "method": method,
        "verification_objective": (
            f"证明需求“{statement}”在规定条件下满足"
            if method == "test" else f"确认用户场景目标“{statement}”实际达成"
        ),
        "precondition": "系统已部署并处于可执行状态",
        "test_condition": (
            "标准运行环境、额定负载和需求边界条件"
            if method == "test" else "典型用户、真实运行场景和代表性任务条件"
        ),
        "input": statement,
        "stimulus": (
            "提交需求并施加正常、异常及人工接管事件"
            if method == "test" else "由运营人员执行任务并触发必要的用户操作"
        ),
        "procedure": "执行需求对应的任务并记录系统响应",
        "expected_result": "系统行为满足需求并留下可审查结果",
        "pass_criteria": "需求约束和行为结果均满足",
    }


__all__ = ["LifecycleTaskRuleRuntime", "LIFECYCLE_TASKS", "OPERATIONAL_FUNCTIONAL_TASKS", "TaskGraphBuilder"]
