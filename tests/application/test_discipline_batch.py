from __future__ import annotations

from pathlib import Path

import pytest

from rflp_lite.adapters.disciplines import discipline_registry
from rflp_lite.application.discipline_batch import (
    evaluate_candidates,
    surrogate_is_valid,
    validate_evaluator_profile,
)
from rflp_lite.application.layout_generation import generate_layout_candidates
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.scheme_retrieval import find_similar_schemes
from rflp_lite.adapters.scheme_sources import read_scheme_rows
from rflp_lite.application.scheme_library import import_scheme_rows
from rflp_lite.application.parameter_rules import create_indicator_envelope
from rflp_lite.domain.errors import ContractViolation

ROOT = Path("src/rflp_lite/resources/examples/concept-design")
PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


class Store:
    def __init__(self):
        self.values = {}

    def load_discipline_evaluation(self, key):
        return self.values.get(key)

    def save_discipline_evaluations(self, values):
        for value in values:
            self.values[value["cache_key"]] = value


def inputs():
    pack = load_domain_pack(PACK)
    rows = read_scheme_rows("fixed-wing-schemes.json", (ROOT / "fixed-wing-schemes.json").read_bytes())
    schemes = import_scheme_rows(pack, rows, "fixture").records
    envelope_payload = __import__("json").loads((ROOT / "fixed-wing-envelope.json").read_text())
    envelope = create_indicator_envelope(pack, envelope_payload, ())
    matches = find_similar_schemes(pack, envelope, schemes)
    candidates = generate_layout_candidates(pack, envelope, schemes, matches)
    return pack, candidates


def test_failure_isolation_and_development_gate():
    pack, candidates = inputs()
    registry = discipline_registry()

    class Failing:
        id = "builtin.structures.v1"
        version = "1"
        source_kind = "analytical"

        def evaluate(self, candidate, profile):
            raise RuntimeError("solver unavailable")

    registry["builtin.structures.v1"] = Failing()
    result = evaluate_candidates(tuple(candidates[:1]), pack, {"id": "dev", "version": 1}, registry, Store())
    by_discipline = {item.discipline: item for item in result.evaluations}
    assert by_discipline["structures"].status == "failed"
    assert by_discipline["aerodynamics"].status == "succeeded"
    assert result.candidate_status[candidates[0].id] == "partial"
    assert result.candidate_formal_status[candidates[0].id] == "partial"


def test_identical_batch_uses_cache():
    pack, candidates = inputs()
    store = Store()
    registry = discipline_registry()
    first = evaluate_candidates(tuple(candidates[:1]), pack, {"id": "dev", "version": 1}, registry, store)
    second = evaluate_candidates(tuple(candidates[:1]), pack, {"id": "dev", "version": 1}, registry, store)
    assert first.candidate_status[candidates[0].id] == "complete"
    assert all(item.status == "cached" for item in second.evaluations)
    assert second.cache_hits == 3


def test_unapproved_profile_cannot_be_formal_passed():
    pack, candidates = inputs()
    result = evaluate_candidates(tuple(candidates[:1]), pack, {"id": "dev", "version": 1}, discipline_registry(), Store())
    assert result.candidate_formal_status[candidates[0].id] == "development"
    evidence = result.evaluations[0].validity
    assert dict(evidence)["validity_status"] == "not_declared"
    assert dict(evidence)["approval_record"] == "missing"
    assert "no customer approval entry" in dict(evidence)["approval_diagnostics"]


def test_surrogate_validity_and_profile_validation():
    assert surrogate_is_valid(
        {"validity_domain": {"mass_kg": {"minimum": 100, "maximum": 200}}, "validation_error": 0.03, "maximum_error": 0.05},
        {"mass_kg": 150},
    )
    assert not surrogate_is_valid(
        {"validity_domain": {"mass_kg": {"minimum": 100, "maximum": 200}}, "validation_error": 0.08, "maximum_error": 0.05},
        {"mass_kg": 150},
    )
    with pytest.raises(ContractViolation):
        validate_evaluator_profile({"id": "bad", "version": 0})


def _complete_profile(dataset_hash="dataset-hash"):
    hashes = {
        "builtin.aerodynamics.v1": "builtin-aerodynamics-v1-low-order-analytical",
        "builtin.structures.v1": "builtin-structures-v1-low-order-analytical",
        "builtin.weight-balance.v1": "builtin-weight-balance-v1-low-order-analytical",
    }
    return {
        "id": "customer-v1",
        "version": 1,
        "approvals": {
            adapter_id: {
                "adapter_version": "1",
                "implementation_hash": implementation_hash,
                "source_kind": "analytical",
                "validity_domain": {"mass_kg": {"minimum": 1, "maximum": 10000}},
                "validation_dataset_id": "gold",
                "validation_dataset_version": "1",
                "validation_dataset_hash": dataset_hash,
                "error_metrics": {},
                "acceptance_limits": {},
                "approved_for_formal": True,
                "approved_by": "customer",
                "approved_at": "2026-09-01T00:00:00Z",
                "basis": "validation report",
            }
            for adapter_id, implementation_hash in hashes.items()
        },
    }


def test_cache_identity_includes_approval_dataset_hash():
    pack, candidates = inputs()
    first = evaluate_candidates(tuple(candidates[:1]), pack, _complete_profile(), discipline_registry(), Store())
    second = evaluate_candidates(tuple(candidates[:1]), pack, _complete_profile("changed"), discipline_registry(), Store())
    assert first.evaluations[0].input_hash != second.evaluations[0].input_hash


def test_complete_approved_profile_can_formal_pass():
    pack, candidates = inputs()
    result = evaluate_candidates(tuple(candidates[:1]), pack, _complete_profile(), discipline_registry(), Store())
    assert result.candidate_formal_status[candidates[0].id] == "passed"
    assert all(item.evidence_status == "formal" for item in result.evaluations)
    evidence = dict(result.evaluations[0].validity)
    assert evidence["validity_status"] == "within_domain"
    assert evidence["validation_dataset_id"] == "gold"
    assert evidence["validation_dataset_hash"] == "dataset-hash"
    assert evidence["approval_status"] == "formal"
