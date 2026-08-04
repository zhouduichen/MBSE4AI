from __future__ import annotations

from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Claim, ModelElement, Relation


_FUNCTION_NAMES = (
    "Save content version",
    "Restore historical version",
    "Record audit event",
)
_LOGICAL_NAMES = ("ContentStore", "RestoreService", "AuditLog")
_PHYSICAL_NAMES = ("SQLiteStore", "JSONContract")


def synthesize_rflp(
    claims: tuple[Claim, ...]
) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]:
    if len(claims) != 3:
        raise InvariantViolation("the local demo requires exactly three claims")
    requirements = tuple(
        ModelElement(
            id=f"req-{index}",
            layer="R",
            kind="requirement",
            name=claim.object.rstrip("."),
            attributes=(("claim_id", claim.id),),
        )
        for index, claim in enumerate(claims, 1)
    )
    functions = tuple(
        ModelElement(
            id=f"fn-{index}",
            layer="F",
            kind="function",
            name=name,
        )
        for index, name in enumerate(_FUNCTION_NAMES, 1)
    )
    logical = tuple(
        ModelElement(
            id=f"logical-{index}",
            layer="L",
            kind="logical-component",
            name=name,
        )
        for index, name in enumerate(_LOGICAL_NAMES, 1)
    )
    physical = tuple(
        ModelElement(
            id=f"physical-{index}",
            layer="P",
            kind="physical-component",
            name=name,
        )
        for index, name in enumerate(_PHYSICAL_NAMES, 1)
    )
    relations: list[Relation] = []
    for index in range(1, 4):
        relations.append(Relation(f"rel-rf-{index}", f"req-{index}", "satisfiedBy", f"fn-{index}"))
        relations.append(Relation(f"rel-fl-{index}", f"fn-{index}", "allocatedTo", f"logical-{index}"))
    relations.extend(
        (
            Relation("rel-lp-1", "logical-1", "realizedBy", "physical-1"),
            Relation("rel-lp-2", "logical-2", "realizedBy", "physical-1"),
            Relation("rel-lp-3", "logical-3", "realizedBy", "physical-2"),
        )
    )
    elements = requirements + functions + logical + physical
    return elements, tuple(sorted(relations, key=lambda item: item.id))

