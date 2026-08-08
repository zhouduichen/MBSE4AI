from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.application.traceability import build_trace_matrix, trace_coverage


def test_trace_matrix_keeps_source_links_for_structured_requirements():
    state = analyze_artifact("requirements.txt", "支持导入 PDF。".encode())
    matrix = build_trace_matrix(state)
    assert {row["predicate"] for row in matrix} >= {"derivedFrom"}
    assert trace_coverage(matrix)["source_complete"] == 100

