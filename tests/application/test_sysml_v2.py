from __future__ import annotations

import pytest

from rflp_lite.application.sysml_v2 import export_sysml_v2_text, import_sysml_v2_text
from rflp_lite.domain.errors import ContractViolation


def _model():
    return {
        "elements": [
            {"id": "req-1", "layer": "R", "kind": "requirement", "name": "恢复"},
            {"id": "fn-1", "layer": "F", "kind": "function", "name": "恢复服务"},
            {"id": "logical-1", "layer": "L", "kind": "logical-component", "name": "服务"},
        ],
        "relations": [
            {"id": "rel-1", "source_id": "req-1", "predicate": "satisfiedBy", "target_id": "fn-1"},
            {"id": "rel-2", "source_id": "fn-1", "predicate": "allocatedTo", "target_id": "logical-1"},
        ],
    }


def test_sysml_v2_subset_round_trips_with_deterministic_text():
    first = export_sysml_v2_text(_model())
    second = export_sysml_v2_text(_model())

    assert first == second
    assert "package RFLP_Lite {" in first
    assert "requirement def req_1;" in first
    assert import_sysml_v2_text(first)["relations"] == [
        {
            "id": "rel-1",
            "source_id": "req-1",
            "predicate": "satisfiedBy",
            "target_id": "fn-1",
        },
        {
            "id": "rel-2",
            "source_id": "fn-1",
            "predicate": "allocatedTo",
            "target_id": "logical-1",
        },
    ]


@pytest.mark.parametrize("text", ("", "package Other {}", "package RFLP_Lite { }"))
def test_sysml_v2_subset_rejects_invalid_text(text: str):
    with pytest.raises(ContractViolation):
        import_sysml_v2_text(text)


def test_sysml_v2_subset_rejects_tampered_hash():
    text = export_sysml_v2_text(_model()).replace("// rflp-model-hash ", "// rflp-model-hash " + "0" * 64 + "\n// ", 1)

    with pytest.raises(ContractViolation, match="hash"):
        import_sysml_v2_text(text)
