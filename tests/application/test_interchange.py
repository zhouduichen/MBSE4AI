from __future__ import annotations

import pytest

from rflp_lite.application.interchange import export_rflp, import_rflp
from rflp_lite.domain.errors import ContractViolation


def _model():
    return {
        "elements": [
            {"id": "req-1", "layer": "R", "kind": "requirement", "name": "恢复"},
            {"id": "fn-1", "layer": "F", "kind": "function", "name": "恢复服务"},
        ],
        "relations": [
            {"id": "rel-1", "source_id": "req-1", "predicate": "satisfiedBy", "target_id": "fn-1"}
        ],
    }


def test_sysml_lite_round_trip_preserves_rflp_model():
    exported = export_rflp(_model())

    assert exported["format"] == "sysml-lite/rflp"
    assert import_rflp(exported) == exported["model"]


@pytest.mark.parametrize(
    "payload",
    (
        {"format": "sysml-v2", "version": 1, "model": _model()},
        {"format": "sysml-lite/rflp", "version": 1, "model": {"elements": [], "relations": [{"source_id": "missing", "target_id": "missing", "predicate": "x"}]}},
    ),
)
def test_sysml_lite_rejects_unsupported_or_invalid_payload(payload):
    with pytest.raises(ContractViolation):
        import_rflp(payload)


def test_sysml_lite_rejects_duplicate_element_ids():
    model = _model()
    model["elements"].append(model["elements"][0].copy())
    with pytest.raises(ContractViolation, match="unique"):
        export_rflp(model)
