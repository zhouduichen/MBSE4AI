"""Project-level context intake for goals and other model seeds."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation, InputRequired
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.repository.port import ModelRepository


class ProjectContextService:
    """Turn a user goal into explicit, reviewable ModelGraph context.

    A goal is kept as both system intent and a candidate requirement.  This
    gives the operational stage a mission/objective to reason over while
    preserving a normal RFLP/V&V path for the goal itself.  All writes use the
    same CAS patch path as the rest of the workbench.
    """

    def __init__(self, repository: ModelRepository, project_id: str):
        self.repository = repository
        self.project_id = str(project_id).strip()
        if not self.project_id:
            raise ContractViolation("project id is required")

    def set_goal(self, goal: str) -> Mapping[str, object]:
        clean = " ".join(str(goal).split()).strip()
        if not clean:
            raise InputRequired("project goal is required")
        graph = self.repository.load_graph(self.project_id)
        system = next(
            (
                item for item in graph.entities
                if item.kind is EntityKind.SYSTEM
                and item.meta.status is not EntityStatus.DEPRECATED
            ),
            None,
        )
        goal_id = f"goal-{canonical_hash(clean)[:16]}"
        operations: list[object] = []
        if system is None:
            system = make_entity(
                EntityKind.SYSTEM,
                f"{self.project_id} 系统",
                _system_goal_payload(clean),
                status=EntityStatus.CANDIDATE,
                producer=Producer.USER,
                confidence=1.0,
                source_ids=(goal_id,),
                revision=graph.revision,
            )
            operations.append(AddEntity(system))
        elif not _protected(system):
            payload = dict(system.payload)
            goals = _unique_strings(payload.get("user_goals", ()))
            if clean not in goals:
                goals.append(clean)
            objectives = _unique_strings(payload.get("objectives", ()))
            if clean not in objectives:
                objectives.append(clean)
            payload.update({
                "mission": clean,
                "objectives": objectives,
                "user_goals": goals,
                "goal_provenance": "user_input",
                "requires_human_review": True,
            })
            if payload != dict(system.payload):
                operations.append(UpdateEntity(system.id, {"payload": payload}))

        requirement = next(
            (
                item for item in graph.entities
                if item.kind is EntityKind.REQUIREMENT
                and item.meta.status is not EntityStatus.DEPRECATED
                and str(item.payload.get("goal_id", "")) == goal_id
            ),
            None,
        )
        if requirement is None:
            requirement = make_entity(
                EntityKind.REQUIREMENT,
                f"用户目标：{clean}",
                {
                    "statement": f"系统应实现：{clean}",
                    "goal_id": goal_id,
                    "goal_text": clean,
                    "source": "user_goal",
                    "level": "stakeholder",
                    "type": "functional",
                    "obligation": "系统应",
                    "verification_method": "demonstration",
                    "requires_human_review": True,
                },
                status=EntityStatus.CANDIDATE,
                producer=Producer.USER,
                confidence=1.0,
                source_ids=(goal_id,),
                revision=graph.revision,
            )
            operations.append(AddEntity(requirement))
        if not any(
            item.source_id == requirement.id
            and item.predicate is RelationPredicate.DERIVED_FROM
            and item.target_id == system.id
            for item in graph.relations
        ):
            operations.append(Relate(requirement.id, RelationPredicate.DERIVED_FROM, system.id))
        if operations:
            patch = Patch.create(
                self.project_id,
                "user.project_goal",
                tuple(operations),
                "用户设定项目目标",
                graph.revision,
            )
            revision = self.repository.append_patch(self.project_id, patch, graph.revision)
        else:
            revision = None
        current = self.repository.load_graph(self.project_id)
        stored_system = current.entity_index[system.id]
        stored_requirement = current.entity_index[requirement.id]
        return {
            "goal": clean,
            "goal_id": goal_id,
            "system": stored_system.as_dict(),
            "requirement": stored_requirement.as_dict(),
            "revision": revision.sequence if revision else current.revision,
            "created": bool(revision),
        }


def _system_goal_payload(goal: str) -> Mapping[str, object]:
    return {
        "mission": goal,
        "system_boundary": {
            "inside": ["待由系统工程分析确定的系统能力"],
            "outside": ["运行环境、外部操作者和未声明的实现细节"],
        },
        "objectives": [goal],
        "user_goals": [goal],
        "goal_provenance": "user_input",
        "environment_assumptions": ["运行环境和外部约束需要由资料或后续证据确认"],
        "exclusions": ["未提供的实现细节不作为事实"],
        "open_questions": [],
        "requires_human_review": True,
    }


def _unique_strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        clean = " ".join(str(item).split()).strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _protected(entity) -> bool:
    return entity.meta.status is EntityStatus.LOCKED or bool(entity.payload.get("user_modified"))


__all__ = ["ProjectContextService"]
