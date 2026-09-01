from rflp_lite.application.mbse_graphviz import compile_graphviz_view
from rflp_lite.application.mbse_matrix import render_matrix_view
from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.mbse_plantuml import compile_plantuml_view
from rflp_lite.application.mbse_render import render_mbse_svg
from rflp_lite.application.mbse_views import (
    compile_mbse_view,
    list_mbse_views,
)
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact


def _model():
    return generate_mbse_revision(
        accept_traceable(analyze_artifact("requirements.txt", "支持导入 PDF。".encode()))
    )["mbse"]


def test_view_registry_has_professional_multi_layout_set():
    views = {item["id"]: item for item in list_mbse_views(_model())}

    assert {
        "environment",
        "stakeholder_hierarchy",
        "requirements_tree",
        "lifecycle",
        "use_case_tree",
        "operational_scenario",
        "function_tree",
        "function_interaction",
        "functional_scenario",
        "logical_tree",
        "logical_interaction",
        "allocation_matrix",
        "physical_interaction",
        "technical_requirements",
        "traceability_matrix",
        "rflp",
    } <= views.keys()
    assert views["environment"]["layout"] == "radial"
    assert views["function_tree"]["layout"] == "tree"
    assert views["function_interaction"]["layout"] == "flow"
    assert views["allocation_matrix"]["compiler"] == "matrix"


def test_graphviz_compiler_uses_view_specific_layout_and_escaped_labels():
    model = _model()
    functional = model["semantic_model"]["sections"]["functional"]
    item = (functional["functions"] or functional["gaps"])[0]
    item["name"] = '输入 "文件"'

    radial = compile_graphviz_view(model, "environment")
    tree = compile_graphviz_view(model, "function_tree")

    assert "rankdir=LR" in radial
    assert "rankdir=TB" in tree
    assert '\\"文件\\"' in tree
    assert "satisfiedBy" in tree or "暂无可用语义" not in tree


def test_plantuml_compilers_keep_sequence_and_activity_semantics():
    model = _model()

    sequence = compile_plantuml_view(model, "operational_scenario")
    activity = compile_plantuml_view(model, "functional_scenario")

    assert sequence.startswith("@startuml") and sequence.rstrip().endswith("@enduml")
    assert "-> system:" in sequence
    assert "partition 功能场景" in activity
    assert ":" in activity


def test_matrix_and_svg_fallbacks_are_available_without_external_engines():
    model = _model()

    matrix = render_matrix_view(model, "allocation_matrix")
    rendered = render_mbse_svg(model, "logical_tree")
    compiled = compile_mbse_view(model, "rflp")

    assert "mbse-matrix-svg" in matrix
    assert "分配矩阵" in matrix
    assert "mbse-professional-svg" in rendered
    assert compiled["compiler"] == "graphviz"
    assert compiled["source"].startswith("digraph MBSE")
