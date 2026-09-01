from dataclasses import dataclass, replace

import pytest

from rflp_lite.adapters.disciplines import AerodynamicsAdapter
from rflp_lite.application.evaluator_approval import (
    formal_approval_for,
    validate_approval_profile,
)
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True)
class ApprovedTestAdapter:
    id: str = "test.aero.v1"
    version: str = "1"
    source_kind: str = "customer_solver"
    implementation_hash: str = "test-aero-implementation"

    def evaluate(self, candidate, profile):
        result = AerodynamicsAdapter().evaluate(candidate, profile)
        return replace(
            result,
            adapter_id=self.id,
            adapter_version=self.version,
            source_kind=self.source_kind,
        )


def complete_profile_for(adapter):
    return {
        "id": "customer-v1",
        "version": 1,
        "approvals": {
            adapter.id: {
                "adapter_version": adapter.version,
                "implementation_hash": adapter.implementation_hash,
                "source_kind": adapter.source_kind,
                "validity_domain": {"mass_kg": {"minimum": 100, "maximum": 2000}},
                "validation_dataset_id": "gold-aero-1",
                "validation_dataset_version": "1",
                "validation_dataset_hash": "dataset-hash",
                "error_metrics": {"lift_to_drag_rmse": 0.02},
                "acceptance_limits": {"lift_to_drag_rmse": 0.05},
                "approved_for_formal": True,
                "approved_by": "customer",
                "approved_at": "2026-09-01T00:00:00Z",
                "basis": "customer validation report",
            }
        },
    }


def test_formal_approval_requires_version_hash_domain_dataset_and_human_basis():
    adapter = ApprovedTestAdapter()
    profile = complete_profile_for(adapter)
    decision = formal_approval_for(adapter, {"id": "aerodynamics"}, profile, {"mass_kg": 500})
    assert decision.approved is True
    assert validate_approval_profile(profile)["approvals"]


def test_changed_implementation_hash_or_out_of_domain_is_development():
    adapter = ApprovedTestAdapter()
    profile = complete_profile_for(adapter)
    changed = replace(adapter, implementation_hash="changed")
    assert formal_approval_for(changed, {"id": "aerodynamics"}, profile, {"mass_kg": 500}).approved is False
    assert formal_approval_for(adapter, {"id": "aerodynamics"}, profile, {"mass_kg": 5000}).approved is False


def test_incomplete_approval_entry_is_rejected():
    with pytest.raises(ContractViolation):
        validate_approval_profile({
            "id": "customer-v1",
            "version": 1,
            "approvals": {"test.aero.v1": {"adapter_version": "1", "approved_for_formal": True}},
        })
