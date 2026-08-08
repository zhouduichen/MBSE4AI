import pytest

from rflp_lite.application.workbench_schema import migrate_workbench_state
from rflp_lite.domain.errors import ContractViolation


def test_migrate_legacy_state_adds_v2_fields_and_regions():
    state = migrate_workbench_state(
        {"schema_version": 1, "spans": [{"id": "s1", "text": "原文"}]}
    )
    assert state["schema_version"] == 2
    assert state["document_regions"][0]["id"] == "s1"
    assert state["structured_requirements"] == []


def test_future_schema_is_rejected():
    with pytest.raises(ContractViolation, match="unsupported workbench schema"):
        migrate_workbench_state({"schema_version": 99})

