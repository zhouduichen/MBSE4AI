"""Comparable benchmark scenarios with one normalized ModelGraph evaluator input."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


class BenchmarkScenario(StrEnum):
    A_BARE_ONE_SHOT = "A_bare_one_shot_full_rflp_vv"
    B_BARE_STAGED = "B_bare_staged_rflp_vv"
    C_HARNESS_NO_VERIFIER = "C_harness_without_verifier"
    D_HARNESS_NO_REPAIR = "D_harness_without_repair"
    E_FULL_HARNESS = "E_full_harness"


@dataclass(frozen=True, slots=True)
class ScenarioContract:
    scenario: BenchmarkScenario
    description: str
    has_verifier: bool
    has_repair: bool
    has_cas: bool


SCENARIO_CONTRACTS = (
    ScenarioContract(BenchmarkScenario.A_BARE_ONE_SHOT, "one-shot full RFLP+V&V model output", False, False, False),
    ScenarioContract(BenchmarkScenario.B_BARE_STAGED, "staged R→F→L→P→V&V output without harness controls", False, False, False),
    ScenarioContract(BenchmarkScenario.C_HARNESS_NO_VERIFIER, "real harness path with verifier disabled", False, True, True),
    ScenarioContract(BenchmarkScenario.D_HARNESS_NO_REPAIR, "real harness path with repair disabled", True, False, True),
    ScenarioContract(BenchmarkScenario.E_FULL_HARNESS, "real harness path with verifier, repair, gates, and CAS", True, True, True),
)


def scenario_contract(value: str | BenchmarkScenario) -> ScenarioContract:
    requested = BenchmarkScenario(value)
    return next(item for item in SCENARIO_CONTRACTS if item.scenario is requested)


def normalize_to_model_graph(value: object, *, project_id: str = "benchmark") -> ModelGraph:
    """Normalize A–E outputs before passing them to the same evaluator."""

    if isinstance(value, ModelGraph):
        return value
    candidate = (
        value.get("graph", value)
        if isinstance(value, Mapping)
        else value
    )
    if isinstance(candidate, ModelGraph):
        return candidate
    if isinstance(candidate, Mapping) and candidate.get("project_id") is not None:
        return _graph_from_mapping(candidate, project_id)
    payload = candidate if isinstance(candidate, Mapping) else {}
    entities = []
    for item in payload.get("requirements", ()) if isinstance(payload, Mapping) else ():
        if not isinstance(item, Mapping):
            continue
        statement = str(item.get("statement", item.get("name", ""))).strip()
        if not statement:
            continue
        entities.append(
            make_entity(
                EntityKind.REQUIREMENT,
                statement,
                {"statement": statement, "verification_method": item.get("verification_method", "")},
                status=EntityStatus.CANDIDATE,
                producer=Producer.LLM,
            )
        )
    return ModelGraph(project_id, tuple(entities), (), 0)


def evaluate_normalized(
    value: object,
    evaluator: Callable[[ModelGraph], Mapping[str, object]],
    *,
    project_id: str = "benchmark",
) -> dict[str, object]:
    graph = normalize_to_model_graph(value, project_id=project_id)
    return {
        "graph": {
            "project_id": graph.project_id,
            "revision": graph.revision,
            "snapshot_hash": graph.snapshot_hash,
            "entities": [item.as_dict() for item in graph.entities],
            "relations": [
                {
                    "id": relation.id,
                    "source_id": relation.source_id,
                    "predicate": relation.predicate.value,
                    "target_id": relation.target_id,
                    "evidence_ids": list(relation.evidence_ids),
                }
                for relation in graph.relations
            ],
        },
        "metrics": dict(evaluator(graph)),
    }


def bare_model_graph(
    case: Mapping[str, object],
    *,
    project_id: str,
    staged: bool,
) -> ModelGraph:
    """Build the observable output of the two bare baselines.

    A/B deliberately bypass the repository, gates, verifier, repair loop and
    CAS.  They still emit typed RFLP+V&V objects, which are immediately fed
    through the same ``ModelGraph`` normalizer/evaluator as harness runs.
    """

    entities = []
    relations: list[Relation] = []

    def add(kind: EntityKind, name: str, payload: Mapping[str, object] | None = None):
        entity = make_entity(
            kind,
            name,
            {
                **(dict(payload) if isinstance(payload, Mapping) else {}),
                "scenario_mode": "bare_staged" if staged else "bare_one_shot",
            },
            status=EntityStatus.CANDIDATE,
            producer=Producer.LLM,
        )
        entities.append(entity)
        return entity

    def relate(source: str, predicate: RelationPredicate, target: str) -> None:
        relations.append(
            Relation(
                f"relation-{len(relations) + 1:04d}",
                source,
                predicate,
                target,
            )
        )

    system = add(
        EntityKind.SYSTEM,
        str(case.get("system", "benchmark system")),
        {"mission": str(case.get("system", "benchmark system"))},
    )
    stakeholders = [
        add(EntityKind.STAKEHOLDER, str(item), {"role": str(item)})
        for item in case.get("stakeholders", ())
        if str(item).strip()
    ]
    lifecycle = [
        add(EntityKind.LIFECYCLE_STAGE, str(item), {"stage": str(item)})
        for item in case.get("lifecycle_stages", ())
        if str(item).strip()
    ]
    scenarios = [
        add(EntityKind.SCENARIO_HYPOTHESIS, str(item), {"scenario": str(item)})
        for item in case.get("scenarios", ())
        if str(item).strip()
    ]
    use_case = add(
        EntityKind.USE_CASE,
        f"执行 {case.get('system', '系统')} 任务",
        {"goal": "完成任务并记录结果"},
    )
    operational = add(
        EntityKind.OPERATIONAL_SCENARIO,
        "典型运行场景",
        {"use_case_id": use_case.id},
    )
    activity = add(
        EntityKind.ACTIVITY,
        "执行任务与异常处置",
        {"branch_types": ["normal", "failure", "alternative", "boundary", "exception"]},
    )
    relate(system.id, RelationPredicate.DERIVED_FROM, use_case.id)
    relate(use_case.id, RelationPredicate.DECOMPOSES, activity.id)
    relate(activity.id, RelationPredicate.DERIVED_FROM, operational.id)
    for stakeholder in stakeholders:
        relate(stakeholder.id, RelationPredicate.PARTICIPATES_IN, use_case.id)
    for item in lifecycle:
        relate(activity.id, RelationPredicate.OCCURS_IN, item.id)
    for item in scenarios:
        relate(use_case.id, RelationPredicate.DERIVED_FROM, item.id)

    for raw_requirement in case.get("requirements", ()):
        if not isinstance(raw_requirement, Mapping):
            continue
        statement = str(raw_requirement.get("statement", "")).strip()
        if not statement:
            continue
        requirement = add(
            EntityKind.REQUIREMENT,
            statement,
            {
                "fixture_id": str(raw_requirement.get("id", "")),
                "statement": statement,
                "obligation": statement,
                "verification_method": "test",
                "source": "bare_scenario",
            },
        )
        function = add(
            EntityKind.FUNCTION,
            f"执行：{statement}",
            {"behavior": statement, "requirement_id": requirement.id},
        )
        logical = add(
            EntityKind.LOGICAL_COMPONENT,
            f"逻辑能力：{statement}",
            {"function_id": function.id, "responsibility": statement},
        )
        physical = add(
            EntityKind.PHYSICAL_BLOCK,
            f"物理实现：{statement}",
            {"logical_id": logical.id, "candidate": True},
        )
        verification = add(
            EntityKind.VERIFICATION_CASE,
            f"验证：{statement}",
            {
                "requirement_ids": [requirement.id],
                "method": "test",
                "precondition": "系统处于可测试状态",
                "test_condition": "标准运行环境和需求边界条件",
                "input": statement,
                "stimulus": "执行需求对应任务",
                "procedure": "执行并记录结果",
                "expected_result": "行为满足需求",
                "pass_criteria": "需求约束满足",
            },
        )
        validation = add(
            EntityKind.VALIDATION_CASE,
            f"确认：{statement}",
            {
                "requirement_ids": [requirement.id],
                "method": "demonstration",
                "precondition": "典型用户场景可用",
                "test_condition": "真实用户和代表性任务条件",
                "input": statement,
                "stimulus": "用户执行典型任务",
                "procedure": "执行场景并收集确认",
                "expected_result": "用户目标达成",
                "pass_criteria": "用户确认通过",
            },
        )
        relate(requirement.id, RelationPredicate.DERIVED_FROM, use_case.id)
        relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id)
        relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id)
        relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id)
        relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id)
        relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id)

    return normalize_to_model_graph(
        {
            "project_id": project_id,
            "revision": 0,
            "entities": [item.as_dict() for item in entities],
            "relations": [
                {
                    "id": item.id,
                    "source_id": item.source_id,
                    "predicate": item.predicate.value,
                    "target_id": item.target_id,
                }
                for item in relations
            ],
        },
        project_id=project_id,
    )


def _graph_from_mapping(value: Mapping[str, object], project_id: str) -> ModelGraph:
    # Benchmark outputs are read-only here; production repository writes still
    # go through Patch/apply_patch. This adapter makes all scenario evaluators
    # consume the same typed graph shape.
    del project_id
    return ModelGraph(
        str(value.get("project_id", "benchmark")),
        tuple(_entity_from_mapping(item) for item in value.get("entities", ()) if isinstance(item, Mapping)),
        tuple(
            Relation(
                str(item.get("id", "relation")),
                str(item.get("source_id", "")),
                RelationPredicate(str(item.get("predicate", RelationPredicate.DERIVED_FROM.value))),
                str(item.get("target_id", "")),
                tuple(str(evidence) for evidence in item.get("evidence_ids", ()) if str(evidence)),
            )
            for item in value.get("relations", ())
            if isinstance(item, Mapping)
        ),
        int(value.get("revision", 0) or 0),
    )


def _entity_from_mapping(value: Mapping[str, object]):
    kind = EntityKind(str(value.get("kind", EntityKind.REQUIREMENT.value)))
    status = EntityStatus(str(value.get("status", EntityStatus.CANDIDATE.value)))
    producer = Producer(str(value.get("producer", Producer.LLM.value)))
    return make_entity(
        kind,
        str(value.get("name", kind.value)),
        value.get("payload", {}) if isinstance(value.get("payload", {}), Mapping) else {},
        status=status,
        producer=producer,
        confidence=value.get("confidence"),
        source_ids=tuple(str(item) for item in value.get("source_ids", ()) if str(item)),
        evidence_ids=tuple(str(item) for item in value.get("evidence_ids", ()) if str(item)),
    )
