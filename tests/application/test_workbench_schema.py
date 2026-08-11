import pytest

from rflp_lite.application.workbench_schema import (
    empty_discovery_state,
    migrate_workbench_state,
)
from rflp_lite.domain.errors import ContractViolation


def test_migrate_legacy_state_adds_v3_fields_regions_and_discovery():
    source = {"schema_version": 1, "spans": [{"id": "s1", "text": "原文"}]}
    state = migrate_workbench_state(source)

    assert source["schema_version"] == 1
    assert state["schema_version"] == 3
    assert state["document_regions"][0]["id"] == "s1"
    assert state["structured_requirements"] == []
    assert state["discovery"] == empty_discovery_state()


def test_migrate_v2_preserves_existing_model_and_adds_empty_discovery():
    source = {
        "schema_version": 2,
        "mbse": {"revision": "old"},
        "rflp": {"elements": [{"id": "req-1"}], "relations": []},
        "scenarios": [{"id": "scenario-1"}],
    }

    state = migrate_workbench_state(source)

    assert state["schema_version"] == 3
    assert state["mbse"] == source["mbse"]
    assert state["rflp"] == source["rflp"]
    assert state["scenarios"] == source["scenarios"]
    assert state["discovery"] == empty_discovery_state()


def test_migrate_v3_is_idempotent_and_preserves_existing_discovery():
    source = {
        "schema_version": 3,
        "discovery": {
            "intake": {"system_name": "城市医疗飞行汽车"},
            "candidate_sets": [{"id": "set-1"}],
        },
        "mbse": {"revision": "accepted"},
    }
    original = {
        "schema_version": 3,
        "discovery": {
            "intake": {"system_name": "城市医疗飞行汽车"},
            "candidate_sets": [{"id": "set-1"}],
        },
        "mbse": {"revision": "accepted"},
    }

    first = migrate_workbench_state(source)
    second = migrate_workbench_state(first)

    assert first == second
    assert first["discovery"] == source["discovery"]
    assert source == original
    assert first["discovery"] is not source["discovery"]


def test_empty_discovery_state_returns_independent_default_fragments():
    first = empty_discovery_state()
    second = empty_discovery_state()

    first["candidate_sets"].append({"id": "candidate-set-1"})

    assert second == {
        "accepted_graph": {"elements": [], "relations": []},
        "candidate_sets": [],
        "coverage": {},
        "diagnostics": [],
        "diagram_specs": [],
        "intake": {},
        "revision": 0,
    }


def test_future_schema_is_rejected():
    with pytest.raises(ContractViolation, match="unsupported workbench schema"):
        migrate_workbench_state({"schema_version": 99})
