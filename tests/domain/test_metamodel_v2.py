import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import ModelGraph, Patch, Relate, UpdateEntity, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.domain.requirements import Requirement


def test_entity_meta_has_stable_typed_identity():
    first = make_entity(EntityKind.SYSTEM, "校园配送系统", producer=Producer.USER)
    second = make_entity(EntityKind.SYSTEM, "校园配送系统", producer=Producer.USER)

    assert first.id == second.id
    assert first.kind is EntityKind.SYSTEM
    assert first.meta.producer is Producer.USER


def test_performance_requirement_keeps_parameter_gap_without_metric():
    requirement = Requirement.from_fields(
        subject="机器人",
        obligation="应支持配送",
        type="performance",
    )

    assert requirement.parameter_gap == "TBD"


def test_model_graph_rejects_duplicate_entities():
    entity = make_entity(EntityKind.SYSTEM, "系统")

    with pytest.raises(ContractViolation, match="entity id duplicated"):
        ModelGraph("p1", (entity, entity))


def test_patch_adds_entity_and_relation_in_one_typed_graph():
    system = make_entity(EntityKind.SYSTEM, "系统")
    function = make_entity(EntityKind.FUNCTION, "配送")
    graph = ModelGraph("p1", (system, function))
    patch = Patch.create(
        "p1",
        "functional.identify",
        (Relate(system.id, RelationPredicate.DECOMPOSES, function.id),),
        "derive function",
        0,
    )

    result = apply_patch(graph, patch)

    assert result.revision == 1
    assert result.relations[0].predicate is RelationPredicate.DECOMPOSES


def test_locked_entity_rejects_automatic_update():
    entity = make_entity(EntityKind.SYSTEM, "系统", status=EntityStatus.LOCKED)
    graph = ModelGraph("p1", (entity,))
    patch = Patch.create(
        "p1", "repair", (UpdateEntity(entity.id, {"payload": {"x": 1}}),), "repair", 0
    )

    with pytest.raises(ContractViolation, match="entity is locked"):
        apply_patch(graph, patch)
