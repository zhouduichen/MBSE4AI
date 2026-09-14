from rflp_lite.application.projections.model_workbench import build_model_workbench_view
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph


def test_model_workbench_groups_real_entities_by_engineering_layer():
    function = make_entity(EntityKind.FUNCTION, "规划配送")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "规划组件")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "计算单元")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证配送")
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认体验")

    view = build_model_workbench_view(ModelGraph("p1", (function, logical, physical, verification, validation)))

    assert [group["id"] for group in view["groups"]] == [
        "system", "functional", "logical", "physical", "assurance",
    ]
    assert view["metrics"]["entity_count"] == 5
    assert {item["id"] for item in view["groups"][1]["entities"]} == {function.id}
    assert {
        item["kind"] for item in view["groups"][4]["entities"]
    } == {"verification_case", "validation_case"}


def test_model_workbench_keeps_empty_groups_explicit():
    view = build_model_workbench_view(ModelGraph("p1"))

    assert all(group["entities"] == [] for group in view["groups"])
    assert all(group["count"] == 0 for group in view["groups"])
    assert view["metrics"]["relation_count"] == 0
