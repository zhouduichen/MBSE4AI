import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate, validate_endpoint_kinds


def test_requirement_satisfied_by_function_is_valid():
    validate_endpoint_kinds(
        RelationPredicate.SATISFIED_BY,
        EntityKind.REQUIREMENT,
        EntityKind.FUNCTION,
    )


def test_physical_satisfied_by_stakeholder_is_invalid():
    with pytest.raises(ContractViolation, match="relation endpoint type invalid"):
        validate_endpoint_kinds(
            RelationPredicate.SATISFIED_BY,
            EntityKind.PHYSICAL_BLOCK,
            EntityKind.STAKEHOLDER,
        )


def test_graph_relation_requires_existing_endpoints():
    source = make_entity(EntityKind.SYSTEM, "系统")
    graph = ModelGraph("p1", (source,))

    with pytest.raises(ContractViolation, match="relation endpoint not found"):
        graph.validate_relation(
            Relation("r1", source.id, RelationPredicate.DECOMPOSES, "missing")
        )
