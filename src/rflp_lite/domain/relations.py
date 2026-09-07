"""Closed relation vocabulary and endpoint validation for ModelGraph."""

from __future__ import annotations

from enum import StrEnum

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.errors import ContractViolation


class RelationPredicate(StrEnum):
    HAS_CONCERN = "hasConcern"
    PARTICIPATES_IN = "participatesIn"
    OCCURS_IN = "occursIn"
    DERIVED_FROM = "derivedFrom"
    REFINES = "refines"
    DECOMPOSES = "decomposes"
    DESCRIBED_BY = "describedBy"
    SATISFIED_BY = "satisfiedBy"
    ALLOCATED_TO = "allocatedTo"
    REALIZED_BY = "realizedBy"
    EXCHANGES_WITH = "exchangesWith"
    CONNECTED_TO = "connectedTo"
    VERIFIED_BY = "verifiedBy"
    VALIDATED_BY = "validatedBy"
    CAUSES = "causes"
    MITIGATED_BY = "mitigatedBy"
    SUPPORTED_BY = "supportedBy"


_ANY = frozenset(EntityKind)
_ENDPOINTS: dict[RelationPredicate, tuple[frozenset[EntityKind], frozenset[EntityKind]]] = {
    RelationPredicate.HAS_CONCERN: (frozenset({EntityKind.STAKEHOLDER, EntityKind.SYSTEM}), frozenset({EntityKind.CONCERN})),
    RelationPredicate.PARTICIPATES_IN: (_ANY, frozenset({EntityKind.OPERATIONAL_SCENARIO, EntityKind.FUNCTIONAL_SCENARIO})),
    RelationPredicate.OCCURS_IN: (frozenset({EntityKind.ACTIVITY, EntityKind.OPERATIONAL_SCENARIO}), frozenset({EntityKind.LIFECYCLE_STAGE})),
    RelationPredicate.DERIVED_FROM: (_ANY, _ANY),
    RelationPredicate.REFINES: (frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT}), _ANY),
    RelationPredicate.DECOMPOSES: (frozenset({EntityKind.SYSTEM, EntityKind.USE_CASE, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT}), _ANY),
    RelationPredicate.DESCRIBED_BY: (_ANY, frozenset({EntityKind.EVIDENCE})),
    RelationPredicate.SATISFIED_BY: (frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION}), frozenset({EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK})),
    RelationPredicate.ALLOCATED_TO: (frozenset({EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT}), frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK})),
    RelationPredicate.REALIZED_BY: (frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.FUNCTION}), frozenset({EntityKind.PHYSICAL_BLOCK, EntityKind.FUNCTION})),
    RelationPredicate.EXCHANGES_WITH: (_ANY, frozenset({EntityKind.INTERFACE, EntityKind.FUNCTIONAL_FLOW})),
    RelationPredicate.CONNECTED_TO: (frozenset({EntityKind.INTERFACE, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}), frozenset({EntityKind.INTERFACE, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK})),
    RelationPredicate.VERIFIED_BY: (frozenset({EntityKind.REQUIREMENT}), frozenset({EntityKind.VERIFICATION_CASE})),
    RelationPredicate.VALIDATED_BY: (frozenset({EntityKind.REQUIREMENT, EntityKind.USE_CASE}), frozenset({EntityKind.VALIDATION_CASE})),
    RelationPredicate.CAUSES: (frozenset({EntityKind.HAZARD, EntityKind.FAILURE_MODE}), _ANY),
    RelationPredicate.MITIGATED_BY: (frozenset({EntityKind.HAZARD, EntityKind.FAILURE_MODE}), frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.VERIFICATION_CASE})),
    RelationPredicate.SUPPORTED_BY: (_ANY, frozenset({EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE})),
}


def endpoint_types(predicate: RelationPredicate) -> tuple[frozenset[EntityKind], frozenset[EntityKind]]:
    return _ENDPOINTS[predicate]


def validate_endpoint_kinds(predicate: RelationPredicate, source: EntityKind, target: EntityKind) -> None:
    allowed_source, allowed_target = endpoint_types(predicate)
    if source not in allowed_source or target not in allowed_target:
        raise ContractViolation(
            f"relation endpoint type invalid: {predicate.value} ({source.value} -> {target.value})"
        )
