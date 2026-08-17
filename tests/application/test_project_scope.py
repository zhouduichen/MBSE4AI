import pytest

from rflp_lite.application.project_scope import (
    bind_project_scope,
    validate_project_references,
    validate_project_scope,
)
from rflp_lite.domain.errors import ContractViolation


def test_binding_is_stable_and_records_workspace():
    state = {"document_regions": [{"id": "region-1", "text": "设计一款牙刷"}]}

    bound = bind_project_scope(state, "toothbrush")

    assert bound["project_scope"]["workspace"] == "toothbrush"
    assert bound["project_scope"]["input_hash"]


def test_scope_rejects_state_from_another_workspace():
    state = bind_project_scope({"document_regions": []}, "aircar")

    with pytest.raises(ContractViolation, match="项目作用域"):
        validate_project_scope(state, "toothbrush")


def test_scope_rejects_requirement_reference_outside_current_state():
    state = {
        "claims": [{"id": "req-local"}],
        "scenarios": [{"id": "scenario-1", "requirement_ids": ["req-foreign"]}],
    }

    with pytest.raises(ContractViolation, match="当前项目不存在"):
        validate_project_references(state)


def test_scope_rejects_trace_link_outside_current_state():
    state = {
        "claims": [{"id": "req-local"}],
        "trace_links": [{"source_id": "req-local", "target_id": "foreign-node"}],
    }

    with pytest.raises(ContractViolation, match="追溯关系"):
        validate_project_references(state)
