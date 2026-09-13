from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage


def test_matrix_requires_complete_predicate_aware_rflp_and_verification_path():
    entities = tuple([
        make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED, evidence_ids=("e1",)),
        make_entity(EntityKind.FUNCTION, "支持配送"),
        make_entity(EntityKind.LOGICAL_COMPONENT, "配送逻辑"),
        make_entity(EntityKind.PHYSICAL_BLOCK, "配送执行器"),
        make_entity(EntityKind.VERIFICATION_CASE, "验证", {"method": "test", "pass_criteria": "通过"}),
        make_entity(EntityKind.VALIDATION_CASE, "确认", {"method": "demonstration", "pass_criteria": "通过"}),
    ])
    requirement, function, logical, physical, verification, validation = entities
    graph = ModelGraph("p1", entities, (
        Relation("r1", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("r2", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("r3", logical.id, RelationPredicate.REALIZED_BY, physical.id),
        Relation("r4", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relation("r5", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    ))

    matrix = build_requirement_coverage(graph)
    row = matrix.rows[0]
    assert row.passed is True
    assert row.paths == ((requirement.id, function.id, logical.id, physical.id),)
    assert matrix.metrics["r_to_f_to_l_to_p_coverage"] == 1.0
    assert matrix.metrics["r_to_v_coverage"] == 1.0
    assert matrix.metrics["r_to_validation_coverage"] == 1.0


def test_matrix_sorting_is_stable_and_collects_all_candidate_paths():
    requirements = [make_entity(EntityKind.REQUIREMENT, name, {"obligation": name}, status=EntityStatus.ACCEPTED) for name in ("B", "A")]
    function = make_entity(EntityKind.FUNCTION, "功能")
    graph = ModelGraph("p1", tuple(requirements + [function]), tuple(
        Relation(f"r{i}", requirement.id, RelationPredicate.SATISFIED_BY, function.id)
        for i, requirement in enumerate(requirements)
    ))

    matrix = build_requirement_coverage(graph)

    assert [row.requirement_id for row in matrix.rows] == sorted(row.requirement_id for row in matrix.rows)
    assert matrix.rows[0].passed is False
