from rflp_lite.application.acceptance_harness import run_customer_acceptance


def test_customer_acceptance_harness_covers_requirements_and_mbse():
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。\n生成3~5套布局草图。".encode())
    assert report["status"] == "passed"
    assert report["smoke_status"] == "passed"
    assert report["formal_status"] == "not_evaluated"
    assert report["checks"]["1.1.traceability"] is True
    assert report["mbse"]["use_cases"] == 2


def test_gold_mismatch_cannot_formally_pass(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text(
        '{"version":2,"requirements":[{"statement":"完全不同","source_text":"完全不同"}]}',
        encoding="utf-8",
    )
    report = run_customer_acceptance(
        "requirements.txt", "支持导入 PDF。".encode(), gold
    )
    assert report["smoke_status"] == "passed"
    assert report["formal_status"] == "failed"
    assert report["extraction_metrics"]["recall"] == 0.0


def test_without_gold_is_smoke_only():
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。".encode())
    assert report["smoke_status"] == "passed"
    assert report["formal_status"] == "not_evaluated"
