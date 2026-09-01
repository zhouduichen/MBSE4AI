import pytest

from rflp_lite.domain.requirement_details import (
    RequirementAttribute,
    RequirementConstraint,
)


def test_attribute_and_constraint_require_sources():
    with pytest.raises(ValueError, match="source_region_ids"):
        RequirementAttribute.from_fields(
            requirement_id="req-1",
            name="速度",
            value="120",
            unit="km/h",
            source_region_ids=(),
        )

    with pytest.raises(ValueError, match="source_region_ids"):
        RequirementConstraint.from_fields(
            requirement_ids=("req-1",),
            constraint_type="performance",
            expression="速度 >= 120 km/h",
            explicitness="explicit",
            source_region_ids=(),
        )


def test_details_are_frozen_and_ids_are_deterministic():
    first = RequirementAttribute.from_fields(
        requirement_id="req-1",
        name="速度",
        value="120",
        unit="km/h",
        source_region_ids=("region-1",),
    )
    second = RequirementAttribute.from_fields(
        requirement_id="req-1",
        name="速度",
        value="120",
        unit="km/h",
        source_region_ids=("region-1",),
    )
    assert first == second
    assert first.id.startswith("attribute-")
    with pytest.raises(AttributeError):
        first.name = "航程"

    constraint = RequirementConstraint.from_fields(
        requirement_ids=("req-2", "req-1"),
        constraint_type="performance",
        expression="速度 >= 120 km/h",
        explicitness="explicit",
        source_region_ids=("region-1",),
    )
    assert constraint.id.startswith("constraint-")
    assert constraint.requirement_ids == ("req-1", "req-2")
    assert constraint.status == "candidate"
    assert constraint.source_region_ids == ("region-1",)


def test_detail_confidence_is_limited_to_zero_one_and_explicitness_is_checked():
    low = RequirementAttribute.from_fields(
        requirement_id="req-1",
        name="速度",
        source_region_ids=("region-1",),
        confidence=-1,
    )
    high = RequirementConstraint.from_fields(
        requirement_ids=("req-1",),
        constraint_type="performance",
        expression="速度 >= 120 km/h",
        explicitness="inferred",
        source_region_ids=("region-1",),
        confidence=2,
    )
    assert low.confidence == 0.0
    assert high.confidence == 1.0
    with pytest.raises(ValueError, match="explicitness"):
        RequirementConstraint.from_fields(
            requirement_ids=("req-1",),
            constraint_type="performance",
            expression="速度 >= 120 km/h",
            explicitness="guess",
            source_region_ids=("region-1",),
        )


def test_structured_requirement_unions_primary_and_additional_sources():
    from rflp_lite.domain.requirements import StructuredRequirement

    requirement = StructuredRequirement.from_fields(
        source_region_ids=("region-1", "region-2", "region-1"),
        additional_source_region_ids=("region-2", "region-3"),
        subject="平台",
        predicate="支持",
        object="需求捕获",
    )

    assert requirement.source_region_id == "region-1"
    assert requirement.source_region_ids == ("region-1", "region-2", "region-3")
