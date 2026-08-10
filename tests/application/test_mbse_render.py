from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.mbse_render import render_mbse_svg
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact


def test_mbse_render_contains_all_semantic_views():
    model = generate_mbse_revision(accept_traceable(analyze_artifact("requirements.txt", "支持导入 PDF。".encode())))["mbse"]
    svg = render_mbse_svg(model)
    assert "Use Case" in svg
    assert "Activity" in svg
    assert "Sequence" in svg


def test_legacy_mbse_sequence_view_uses_interaction_renderer():
    model = generate_mbse_revision(
        accept_traceable(analyze_artifact("requirements.txt", "支持导入 PDF。".encode()))
    )["mbse"]
    svg = render_mbse_svg(model, "sequence")
    assert "sequence-svg" in svg
    assert "marker-end=\"url(#arrow-filled)\"" in svg
    assert "stroke-dasharray=\"6 5\"" in svg
