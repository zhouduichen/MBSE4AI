"""Deterministic offline runtime used when no model profile is configured."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse


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


def _first(context, kind: EntityKind):
    return next((item for item in context.entities if item.kind is kind), None)


class RuleRuntime:
    """Create reviewable candidates from context without inventing source facts."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        if request.task_id.startswith("vertical."):
            return VerticalRuleRuntime().execute(request)
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
        patch = Patch.create(context.project_id, request.task_id, tuple(operations), f"离线规则生成 {kind.value} 候选", context.revision)
        return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch, diagnostics=("offline:rule-runtime",))


class VerticalRuleRuntime:
    """Concrete offline generator used to exercise the product path.

    This is intentionally not an acceptance substitute for a configured LLM.
    It provides a complete, editable graph for local development without
    creating the placeholder entities used by the legacy task runtime.
    """

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        context = request.context_bundle
        index = {item.id: item for item in context.entities}
        operations: list[object] = []
        added: dict[str, object] = {}
        relation_keys = {
            (item.source_id, item.predicate, item.target_id)
            for item in context.relations
        }

        def find(kind: EntityKind, name: str):
            return next(
                (
                    item for item in tuple(index.values()) + tuple(added.values())
                    if item.kind is kind and item.meta.name == name
                ),
                None,
            )

        def add(kind: EntityKind, name: str, payload: dict[str, object]):
            existing = find(kind, name)
            if existing is not None:
                return existing
            entity = make_entity(
                kind,
                name,
                payload,
                status=EntityStatus.VALIDATED,
                producer=Producer.RULE,
                confidence=0.8,
                revision=context.revision,
            )
            if entity.id not in index and entity.id not in added:
                added[entity.id] = entity
                operations.append(AddEntity(entity))
            return entity

        def relate(source, predicate: RelationPredicate, target):
            if source is None or target is None:
                return
            key = (source.id, predicate, target.id)
            if key in relation_keys:
                return
            relation_keys.add(key)
            operations.append(Relate(source.id, predicate, target.id))

        requirements = [
            item for item in context.entities
            if item.kind is EntityKind.REQUIREMENT
            and item.meta.status is not EntityStatus.DEPRECATED
        ]
        if request.task_id == "vertical.requirements":
            seed = requirements[0].meta.name if requirements else context.project_id
            system = next((item for item in context.entities if item.kind is EntityKind.SYSTEM), None)
            system = system or add(EntityKind.SYSTEM, f"{seed} 系统", {
                "mission": f"完成{seed}",
                "system_boundary": {"inside": ["核心服务能力"], "outside": ["运行环境"]},
                "objectives": [f"满足{seed}"],
                "environment_assumptions": ["运行环境可用"],
                "exclusions": ["不预设具体厂商"] ,
                "open_questions": [],
            })
            stakeholder = next((item for item in context.entities if item.kind is EntityKind.STAKEHOLDER), None)
            stakeholder = stakeholder or add(EntityKind.STAKEHOLDER, "系统使用者", {"role": "使用与验收"})
            scenario = next((item for item in context.entities if item.kind is EntityKind.OPERATIONAL_SCENARIO), None)
            scenario = scenario or add(EntityKind.OPERATIONAL_SCENARIO, "典型运行场景", {
                "actor_ids": [stakeholder.id],
                "steps": ["提出任务", "系统执行任务", "反馈结果"],
                "exchanges": [],
                "internal_component_ids": [],
            })
            relate(system, RelationPredicate.DECOMPOSES, stakeholder)
            relate(stakeholder, RelationPredicate.PARTICIPATES_IN, scenario)
            for requirement in requirements:
                relate(requirement, RelationPredicate.DERIVED_FROM, scenario)
        elif request.task_id == "vertical.functional":
            for requirement in requirements:
                function = add(EntityKind.FUNCTION, f"执行：{requirement.meta.name[:36]}", {
                    "behavior": f"实现{requirement.meta.name}",
                    "inputs": [],
                    "outputs": ["执行结果"],
                })
                relate(requirement, RelationPredicate.SATISFIED_BY, function)
            functions = [item for item in tuple(index.values()) + tuple(added.values()) if item.kind is EntityKind.FUNCTION]
            flow = add(EntityKind.FUNCTIONAL_FLOW, "任务信息交互流", {"direction": "双向", "content": "任务与结果"})
            scenario = add(EntityKind.FUNCTIONAL_SCENARIO, "完成核心功能场景", {"function_ids": [item.id for item in functions], "steps": ["输入", "处理", "输出"]})
            for function in functions:
                relate(function, RelationPredicate.EXCHANGES_WITH, flow)
                relate(function, RelationPredicate.DERIVED_FROM, scenario)
        elif request.task_id == "vertical.logical":
            functions = [item for item in context.entities if item.kind is EntityKind.FUNCTION]
            for function in functions:
                logical = add(EntityKind.LOGICAL_COMPONENT, f"逻辑服务：{function.meta.name[:30]}", {
                    "responsibility": function.meta.name,
                    "interfaces": [],
                })
                relate(function, RelationPredicate.ALLOCATED_TO, logical)
                interface = add(EntityKind.INTERFACE, f"功能接口：{function.meta.name[:24]}", {
                    "protocol": "logical-message",
                    "exchanges": ["request", "response"],
                })
                relate(function, RelationPredicate.EXCHANGES_WITH, interface)
                relate(logical, RelationPredicate.CONNECTED_TO, interface)
        elif request.task_id == "vertical.physical":
            logical_components = [item for item in context.entities if item.kind is EntityKind.LOGICAL_COMPONENT]
            for logical in logical_components:
                physical = add(EntityKind.PHYSICAL_BLOCK, f"物理实现：{logical.meta.name[:30]}", {
                    "candidate_type": "可部署执行单元",
                    "solution_class": "领域适配实现",
                    "constraints": ["满足对应逻辑职责"],
                    "rationale": f"承载{logical.meta.name}",
                })
                relate(logical, RelationPredicate.ALLOCATED_TO, physical)
        elif request.task_id == "vertical.verification_validation":
            for requirement in requirements:
                verification = add(EntityKind.VERIFICATION_CASE, f"验证：{requirement.meta.name[:32]}", {
                    "method": "test",
                    "pass_criteria": f"测试结果满足：{requirement.meta.name}",
                    "requirement_ids": [requirement.id],
                    "scenario_ids": [],
                })
                validation = add(EntityKind.VALIDATION_CASE, f"确认：{requirement.meta.name[:32]}", {
                    "method": "demonstration",
                    "pass_criteria": f"用户场景确认：{requirement.meta.name}",
                    "requirement_ids": [requirement.id],
                    "scenario_ids": [],
                })
                relate(requirement, RelationPredicate.VERIFIED_BY, verification)
                relate(requirement, RelationPredicate.VALIDATED_BY, validation)
        else:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:vertical-no-op",))

        if not operations:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:vertical-idempotent",))
        patch = Patch.create(
            context.project_id,
            request.task_id,
            tuple(operations),
            f"离线纵向生成 {request.task_id}",
            context.revision,
        )
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            patch=patch,
            diagnostics=("offline:vertical-runtime",),
        )
