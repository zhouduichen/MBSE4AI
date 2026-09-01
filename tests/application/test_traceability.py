from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.application.traceability import build_trace_matrix, trace_coverage


def test_trace_matrix_keeps_source_links_for_structured_requirements():
    state = analyze_artifact("requirements.txt", "支持导入 PDF。".encode())
    matrix = build_trace_matrix(state)
    assert {row["predicate"] for row in matrix} >= {"derivedFrom"}
    assert trace_coverage(matrix)["source_complete"] == 100


def test_trace_matrix_covers_details_history_and_mbse_elements():
    state = {
        "structured_requirements": [{"id": "req-1", "source_region_id": "region-1", "status": "accepted"}],
        "requirement_attributes": [{"id": "attribute-1", "requirement_id": "req-1", "status": "accepted"}],
        "requirement_constraints": [{"id": "constraint-1", "requirement_ids": ["req-1"], "status": "accepted"}],
        "retrieval_suggestions": [{"id": "suggestion-1", "record_id": "history-1", "requirement_id": "req-1", "kind": "requirement_history", "status": "accepted"}],
        "mbse": {"use_cases": [{"id": "use-case-1", "requirement_ids": ["req-1"], "status": "accepted"}], "trace_links": []},
    }
    matrix = build_trace_matrix(state)
    triples = {(item["source_id"], item["predicate"], item["target_id"]) for item in matrix}
    assert ("req-1", "representedBy", "attribute-1") in triples
    assert ("req-1", "constrainedBy", "constraint-1") in triples
    assert ("history-1", "similarTo", "req-1") in triples
    assert ("req-1", "refines", "use-case-1") in triples
    assert trace_coverage(matrix, total=1)["source_complete"] == 100
