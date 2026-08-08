from __future__ import annotations

import json

import pytest

from rflp_lite.application.demo import run_demo
from rflp_lite.application.profile_packs import (
    export_run_record,
    load_profile,
    save_profile,
    validate_profile_payload,
)
from rflp_lite.application.run_catalog import load_run
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.profile import Profile


def test_profile_payload_is_schema_and_domain_validated(tmp_path):
    payload = {
        "name": "editor",
        "solver": "heuristic",
        "seed": 7,
        "candidate_limit": 2,
        "timeout_seconds": 10,
    }

    assert validate_profile_payload(payload) == payload
    save_profile(tmp_path, payload)
    assert load_profile(tmp_path) == payload
    assert json.loads((tmp_path / "profile.json").read_text()) == payload


def test_profile_rejects_unknown_or_invalid_fields():
    with pytest.raises(ContractViolation):
        validate_profile_payload({"solver": "unknown"})
    with pytest.raises(ContractViolation):
        validate_profile_payload({"name": "x", "solver": "heuristic", "seed": 0})


def test_export_run_record_is_mlflow_mappable_json(tmp_path):
    record = load_run(tmp_path, run_demo(tmp_path, Profile()).result_hash)

    exported = export_run_record(record)

    assert exported["format"] == "rflp-lite-run"
    assert exported["result_hash"] == record.result_hash
    assert exported["manifest"] == record.manifest
    assert "simulation.json" in exported["outputs"]
