from __future__ import annotations

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Baseline, ModelElement, Relation


def _assert_unique(values: tuple[object, ...], label: str) -> None:
    ids = [getattr(value, "id") for value in values]
    if len(ids) != len(set(ids)):
        raise InvariantViolation(f"duplicate {label} id")


def approve_baseline(
    elements: tuple[ModelElement, ...], relations: tuple[Relation, ...]
) -> Baseline:
    ordered_elements = tuple(sorted(elements, key=lambda item: item.id))
    ordered_relations = tuple(sorted(relations, key=lambda item: item.id))
    _assert_unique(ordered_elements, "element")
    _assert_unique(ordered_relations, "relation")
    if any(element.status != "approved" for element in ordered_elements):
        raise InvariantViolation("baseline contains a non-approved element")
    element_ids = {element.id for element in ordered_elements}
    if any(
        relation.source_id not in element_ids or relation.target_id not in element_ids
        for relation in ordered_relations
    ):
        raise InvariantViolation("baseline relation references an unknown element")
    payload = (
        ("elements", ordered_elements),
        ("relations", ordered_relations),
    )
    digest = canonical_hash(payload)
    return Baseline(
        id=f"baseline-{digest[:12]}",
        status="approved",
        elements=ordered_elements,
        relations=ordered_relations,
        payload=payload,
        hash=digest,
    )

