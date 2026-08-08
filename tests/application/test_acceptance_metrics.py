from rflp_lite.application.acceptance_metrics import evaluate_requirement_extraction


def test_extraction_metrics_use_statement_and_source_not_generated_id():
    expected = ({"id": "REQ-1", "statement": "导入 PDF", "source_region_id": "region-1"},)
    actual = ({"id": "requirement-1", "statement": "导入 PDF", "source_region_id": "region-1"},)
    report = evaluate_requirement_extraction(actual, expected)
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["provenance_complete"] == 100

