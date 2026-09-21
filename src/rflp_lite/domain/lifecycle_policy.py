"""Authority-aware entity lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rflp_lite.domain.entities import EntityStatus, Producer
from rflp_lite.domain.errors import ContractViolation


class LifecycleActor(StrEnum):
    LLM = "llm"
    VERIFIER = "verifier"
    USER = "user"
    ACCEPTANCE_POLICY = "acceptance_policy"
    TASK = "task"


@dataclass(frozen=True, slots=True)
class LifecycleTransitionDecision:
    allowed: bool
    previous: EntityStatus
    target: EntityStatus
    actor: LifecycleActor
    reason: str = ""


_TRANSITION_ACTORS = {
    (EntityStatus.CANDIDATE, EntityStatus.VALIDATED): frozenset({LifecycleActor.VERIFIER}),
    (EntityStatus.CANDIDATE, EntityStatus.ACCEPTED): frozenset({LifecycleActor.USER, LifecycleActor.ACCEPTANCE_POLICY}),
    (EntityStatus.VALIDATED, EntityStatus.ACCEPTED): frozenset({LifecycleActor.USER, LifecycleActor.ACCEPTANCE_POLICY}),
    (EntityStatus.ACCEPTED, EntityStatus.LOCKED): frozenset({LifecycleActor.USER}),
    (EntityStatus.LOCKED, EntityStatus.ACCEPTED): frozenset({LifecycleActor.USER}),
    (EntityStatus.CANDIDATE, EntityStatus.REJECTED): frozenset({LifecycleActor.USER}),
    (EntityStatus.VALIDATED, EntityStatus.REJECTED): frozenset({LifecycleActor.USER}),
    (EntityStatus.ACCEPTED, EntityStatus.REJECTED): frozenset({LifecycleActor.USER}),
    (EntityStatus.ACCEPTED, EntityStatus.CANDIDATE): frozenset({LifecycleActor.USER}),
    (EntityStatus.VALIDATED, EntityStatus.CANDIDATE): frozenset({LifecycleActor.USER}),
}


def _status(value: EntityStatus | str) -> EntityStatus:
    try:
        return value if isinstance(value, EntityStatus) else EntityStatus(str(value))
    except ValueError as exc:
        raise ContractViolation(f"unsupported lifecycle status: {value}") from exc


def _actor(value: LifecycleActor | str) -> LifecycleActor:
    try:
        return value if isinstance(value, LifecycleActor) else LifecycleActor(str(value))
    except ValueError as exc:
        raise ContractViolation(f"unsupported lifecycle authority: {value}") from exc


def transition_status(
    current: EntityStatus | str,
    target: EntityStatus | str,
    actor: LifecycleActor | str,
    *,
    force_transition: bool = False,
) -> LifecycleTransitionDecision:
    previous = _status(current)
    next_status = _status(target)
    authority = _actor(actor)
    if previous is next_status:
        if force_transition:
            raise ContractViolation("lifecycle transition must change status")
        return LifecycleTransitionDecision(True, previous, next_status, authority, "no-op")
    allowed = _TRANSITION_ACTORS.get((previous, next_status), frozenset())
    if authority not in allowed:
        raise ContractViolation(
            f"lifecycle authority {authority.value} cannot transition "
            f"{previous.value} -> {next_status.value}"
        )
    return LifecycleTransitionDecision(True, previous, next_status, authority)


def validate_patch_lifecycle(graph, patch) -> None:
    """Reject lifecycle metadata writes that bypass an explicit authority."""

    authority = _actor(getattr(patch, "authority", LifecycleActor.TASK.value))
    if authority is LifecycleActor.TASK:
        for operation in patch.operations:
            if hasattr(operation, "field_patch") and {
                "status", "producer",
            } & set(operation.field_patch):
                raise ContractViolation(
                    "lifecycle authority required for status/producer mutation"
                )
    index = graph.entity_index
    for operation in patch.operations:
        if hasattr(operation, "entity"):
            entity = operation.entity
            if entity.meta.producer is Producer.LLM and entity.meta.status is not EntityStatus.CANDIDATE:
                if authority is not LifecycleActor.VERIFIER:
                    raise ContractViolation("LLM-created entities must start as candidate")
            continue
        if not hasattr(operation, "field_patch"):
            continue
        entity = index.get(operation.entity_id)
        if entity is None:
            continue
        fields = set(operation.field_patch)
        if "status" in fields:
            target = _status(operation.field_patch["status"])
            transition_status(entity.meta.status, target, authority)
            if entity.meta.status is EntityStatus.LOCKED and not (
                authority is LifecycleActor.USER and patch.task_id == "review.unlock"
            ):
                raise ContractViolation("only user review unlock may leave locked status")
        if "producer" in fields:
            try:
                producer = Producer(str(operation.field_patch["producer"]))
            except ValueError as exc:
                raise ContractViolation("unsupported entity producer") from exc
            if authority is LifecycleActor.VERIFIER and producer is not entity.meta.producer:
                raise ContractViolation("verifier cannot change producer provenance")
            if authority not in {LifecycleActor.USER, LifecycleActor.ACCEPTANCE_POLICY}:
                raise ContractViolation("only user or acceptance policy may change producer")


__all__ = [
    "LifecycleActor",
    "LifecycleTransitionDecision",
    "transition_status",
    "validate_patch_lifecycle",
]
