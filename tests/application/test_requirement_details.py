from rflp_lite.application.requirement_details import extract_explicit_details


def test_extracts_range_unit_and_prohibition():
    requirement = {
        "id": "req-1",
        "statement": "系统巡航速度应不低于120 km/h，且不得超过160 km/h",
        "source_region_ids": ["region-1"],
    }
    attributes, constraints = extract_explicit_details(
        (requirement,), {"region-1": requirement["statement"]}
    )
    assert any(item.name == "巡航速度" and item.unit == "km/h" for item in attributes)
    assert {item.expression for item in constraints} == {
        "巡航速度 >= 120 km/h",
        "巡航速度 <= 160 km/h",
    }
    assert all(item.explicitness == "explicit" for item in constraints)
