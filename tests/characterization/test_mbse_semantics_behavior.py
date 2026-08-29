from rflp_lite.application.mbse_semantics import build_mbse_semantic_model
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact


def test_mbse_characterization_records_layers_and_explicit_gaps() -> None:
    state = accept_traceable(analyze_artifact("requirements.txt", "系统必须支持备份。".encode()))
    model = build_mbse_semantic_model(state, revision=3, provenance={"producer": "test"})

    assert set(("operational", "functional", "logical", "physical")) <= set(model["sections"])
    assert model["sections"]["operational"]["stakeholders"]
    assert model["sections"]["functional"]["gaps"]
    assert model["sections"]["logical"]["gaps"]
    assert model["sections"]["physical"]["gaps"]
