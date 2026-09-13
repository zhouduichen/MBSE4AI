"""Task-level offline semantics for the complete 23-task lifecycle.

This runtime is deliberately small and deterministic.  It creates editable
typed candidates from the context already assembled by ``WorkflowRunner``;
the configured structured model runtime remains the provider path for LLM
execution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionRequest, TaskExecutionResponse


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
        self.entities[entity.id] = Entity(entity.meta, payload)
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
        return builder.response("生命周期任务补全功能需求")


__all__ = ["LifecycleTaskRuleRuntime", "OPERATIONAL_FUNCTIONAL_TASKS", "TaskGraphBuilder"]
