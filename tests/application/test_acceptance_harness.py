from rflp_lite.application.acceptance_harness import run_customer_acceptance


def test_customer_acceptance_harness_covers_requirements_and_mbse():
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。\n生成3~5套布局草图。".encode())
    assert report["status"] == "passed"
    assert report["checks"]["1.1.traceability"] is True
    assert report["mbse"]["use_cases"] == 2

