import pytest

from rflp_lite.application.mbse_exchange import export_mbse_json, export_mbse_sysml_v2_text, import_mbse_json, import_mbse_sysml_v2_text
from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact
from rflp_lite.domain.errors import ContractViolation


def _model():
    return generate_mbse_revision(accept_traceable(analyze_artifact("requirements.txt", "支持导入 PDF。".encode())))["mbse"]


def test_mbse_json_and_sysml_round_trip():
    model = _model()
    payload = export_mbse_json(model)
    assert import_mbse_json(payload)["use_cases"] == model["use_cases"]
    text = export_mbse_sysml_v2_text(model)
    assert import_mbse_sysml_v2_text(text)["messages"] == model["messages"]


def test_mbse_exchange_hash_is_checked():
    payload = export_mbse_json(_model())
    payload["model_hash"] = "0" * 64
    with pytest.raises(ContractViolation, match="model_hash"):
        import_mbse_json(payload)

