from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def test_traceability_marks_invalid_predicate_and_missing_stages():
    requirement = make_entity(EntityKind.REQUIREMENT, "Control response", status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "Control")
    graph = ModelGraph("p1", (requirement, function), (Relation("bad", requirement.id, RelationPredicate.DERIVED_FROM, function.id),))
    view = build_traceability_view(graph)
    assert view["rows"][0]["status"] == "INVALID_PREDICATE"
    assert "invalid_predicate" in view["rows"][0]["gaps"]


def test_traceability_matrix_has_a_row_for_candidate_requirements():
    requirements = tuple(make_entity(EntityKind.REQUIREMENT, f"R{index}") for index in range(3))
    view = build_traceability_view(ModelGraph("p1", requirements, ()))
    assert [item["requirement_id"] for item in view["rows"]] == sorted(item.id for item in requirements)
    assert all(item["status"] == "BLOCKED" for item in view["rows"])


def test_technical_requirement_reuses_root_rflp_path_and_adds_physical_target():
    root = make_entity(EntityKind.REQUIREMENT, "系统功耗需求", status=EntityStatus.ACCEPTED)
    technical = make_entity(
        EntityKind.REQUIREMENT,
        "执行单元技术约束",
        {"level": "technical", "constraints": {"max_power_w": 50}},
        status=EntityStatus.VALIDATED,
    )
    function = make_entity(EntityKind.FUNCTION, "执行任务", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器", status=EntityStatus.VALIDATED)
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "执行单元", status=EntityStatus.VALIDATED)
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证技术约束", status=EntityStatus.VALIDATED)
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认技术约束", status=EntityStatus.VALIDATED)
    graph = ModelGraph(
        "p1",
        (root, technical, function, logical, physical, verification, validation),
        (
            Relation("r-f", root.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            Relation("t-r", technical.id, RelationPredicate.DERIVED_FROM, root.id),
            Relation("t-p", technical.id, RelationPredicate.SATISFIED_BY, physical.id),
            Relation("t-v", technical.id, RelationPredicate.VERIFIED_BY, verification.id),
            Relation("t-va", technical.id, RelationPredicate.VALIDATED_BY, validation.id),
        ),
    )

    row = next(item for item in build_traceability_view(graph)["rows"] if item["requirement_id"] == technical.id)

    assert row["functions"] == (function.id,)
    assert row["logical_components"] == (logical.id,)
    assert row["physical_blocks"] == (physical.id,)
    assert row["status"] == "PASS"
