from rflp_lite.domain.entities import EntityKind
from rflp_lite.methodology.tasks import output_contract, task_catalog
from rflp_lite.methodology.vv_contract import VV_PLAN_FIELDS, missing_vv_plan_fields


def test_missing_vv_plan_fields_is_ordered_and_explicit():
    assert missing_vv_plan_fields({"method": "test", "pass_criteria": "通过"}) == (
        "verification_objective", "precondition", "test_condition", "input",
        "stimulus", "procedure", "expected_result",
    )


def test_vv_payload_schema_requires_executable_fields():
    task = next(item for item in task_catalog() if item.id == "verification_validation")
    schemas = output_contract(task)["x-payload-schemas"]
    assert schemas[EntityKind.VERIFICATION_CASE.value]["required"] == list(VV_PLAN_FIELDS)
    assert schemas[EntityKind.VALIDATION_CASE.value]["required"] == list(VV_PLAN_FIELDS)
