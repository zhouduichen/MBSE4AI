from rflp_lite.domain.requirements import StructuredRequirement


def test_structured_requirement_id_is_deterministic_and_provenance_aware():
    first = StructuredRequirement.from_fields(
        source_region_ids=("region-1",),
        subject="平台",
        predicate="支持",
        object="需求捕获",
    )
    second = StructuredRequirement.from_fields(
        source_region_ids=("region-1",),
        subject="平台",
        predicate="支持",
        object="需求捕获",
    )
    assert first == second
    assert first.id.startswith("REQ-")
    assert first.status == "candidate"

