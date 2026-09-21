"""Write-scope policy for model-generated patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.relations import RelationPredicate


@dataclass(frozen=True, slots=True)
class PatchPolicy:
    """The maximum write authority granted to one TaskSpec.

    ``allowed_entity_scope`` accepts ``context``, ``context_and_outputs`` or a
    concrete iterable of entity ids.  The latter is useful for repair tasks
    that are intentionally narrower than a phase's normal context.
    """

    writable_kinds: frozenset[EntityKind] = frozenset()
    writable_fields: frozenset[str] = frozenset()
    allowed_predicates: frozenset[RelationPredicate] = frozenset()
    allowed_entity_scope: str | frozenset[str] = "context_and_outputs"
    max_operations: int | None = None

    @classmethod
    def for_task(
        cls,
        input_kinds: Iterable[EntityKind],
        output_kinds: Iterable[EntityKind],
        *,
        allowed_predicates: Iterable[RelationPredicate] | None = None,
    ) -> "PatchPolicy":
        del input_kinds
        return cls(
            writable_kinds=frozenset(output_kinds),
            writable_fields=frozenset({"name", "status", "confidence", "payload", "lifecycle_ids", "evidence_ids"}),
            allowed_predicates=(
                frozenset()
                if allowed_predicates is None
                else frozenset(allowed_predicates)
            ),
        )
