import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import Deprecate, ModelGraph, Patch, UpdateEntity, apply_patch
from rflp_lite.domain.lifecycle_policy import LifecycleActor, transition_status


def test_lifecycle_authority_is_explicit():
    decision = transition_status(
        EntityStatus.CANDIDATE,
        EntityStatus.VALIDATED,
        LifecycleActor.VERIFIER,
    )

    assert decision.allowed is True
    assert decision.actor is LifecycleActor.VERIFIER


def test_llm_cannot_validate_and_user_cannot_unlock_without_locked_state():
    with pytest.raises(ContractViolation, match="authority"):
        transition_status(EntityStatus.CANDIDATE, EntityStatus.VALIDATED, LifecycleActor.LLM)
    with pytest.raises(ContractViolation, match="transition"):
        transition_status(EntityStatus.ACCEPTED, EntityStatus.ACCEPTED, LifecycleActor.USER, force_transition=True)


def test_generic_patch_cannot_set_status_or_producer():
    entity = make_entity(EntityKind.REQUIREMENT, "需求")
    graph = ModelGraph("p1", (entity,))
    patch = Patch.create(
        "p1",
        "generic.patch",
        (UpdateEntity(entity.id, {"status": EntityStatus.ACCEPTED.value}),),
        "bypass review",
        graph.revision,
    )

    with pytest.raises(ContractViolation, match="lifecycle authority"):
        apply_patch(graph, patch)


def test_verifier_can_only_promote_candidate_to_validated():
    entity = make_entity(EntityKind.REQUIREMENT, "需求")
    graph = ModelGraph("p1", (entity,))
    patch = Patch.create(
        "p1",
        "verifier.validate",
        (UpdateEntity(entity.id, {"status": EntityStatus.VALIDATED.value}),),
        "validator passed",
        graph.revision,
        authority=LifecycleActor.VERIFIER.value,
    )

    result = apply_patch(graph, patch)

    assert result.entity_index[entity.id].meta.status is EntityStatus.VALIDATED


def test_llm_cannot_deprecate_an_existing_entity():
    entity = make_entity(EntityKind.REQUIREMENT, "需求")
    graph = ModelGraph("p1", (entity,))
    patch = Patch.create(
        "p1",
        "llm.patch",
        (Deprecate(entity.id),),
        "模型建议废弃",
        graph.revision,
        authority=LifecycleActor.LLM.value,
    )

    with pytest.raises(ContractViolation, match="LLM cannot change lifecycle status"):
        apply_patch(graph, patch)
