from pathlib import Path

import pytest

from rflp_lite.application.acceptance_gold import load_gold_contract, validate_gold_payload
from rflp_lite.application.acceptance_harness import run_customer_acceptance
from rflp_lite.domain.errors import ContractViolation


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt"
GOLD = ROOT / "src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json"


def test_gold_tree_rejects_unknown_child_and_duplicate_child():
    base = {
        "version": 3,
        "corpus_mode": "complete",
        "details_mode": "complete",
        "requirements": [
            {
                "key": "REQ-1",
                "statement": "支持导入 PDF",
                "source_anchor": "支持导入 PDF",
                "parent_key": "1.1",
                "details": [],
            },
            {
                "key": "REQ-2",
                "statement": "生成布局",
                "source_anchor": "生成布局",
                "parent_key": "1.1",
                "details": [],
            },
        ],
    }
    with pytest.raises(ContractViolation, match="unknown"):
        validate_gold_payload({**base, "tree": [{"key": "1.1", "title": "需求", "children": ["REQ-MISSING"]}]})
    with pytest.raises(ContractViolation, match="multiple parents"):
        validate_gold_payload({
            **base,
            "tree": [
                {"key": "1.1", "title": "需求", "children": ["REQ-1", "REQ-2"]},
                {"key": "2.1", "title": "布局", "children": ["REQ-1"]},
            ],
        })


def test_gold_rejects_3x_scope_entries():
    with pytest.raises(ContractViolation, match="3.x"):
        validate_gold_payload({
            "version": 3,
            "corpus_mode": "complete",
            "details_mode": "complete",
            "requirements": [{
                "key": "REQ-3.1-CAD",
                "statement": "驱动 CAD",
                "source_anchor": "驱动 CAD",
                "area": "3.1",
                "details": [],
            }],
        })


def test_customer_corpus_is_atomic_and_excludes_3x():
    lines = [line.strip() for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 29
    assert not any(token in CORPUS.read_text(encoding="utf-8") for token in ("3.1", "3.2", "3.3"))
    contract = load_gold_contract(GOLD)
    assert len(contract.requirements) == len(lines)
    assert {node["key"] for node in contract.tree} == {"1.1", "1.2", "2.1", "2.2"}


def test_acceptance_report_summarizes_four_parent_nodes():
    report = run_customer_acceptance(CORPUS.name, CORPUS.read_bytes(), GOLD)
    assert report["formal_status"] == "passed"
    assert report["extraction_metrics"]["matched"] == 29
    tree = {item["key"]: item for item in report["acceptance_tree"]}
    assert set(tree) == {"1.1", "1.2", "2.1", "2.2"}
    assert all(item["missing"] == [] and item["extra"] == [] and item["status"] == "passed" for item in tree.values())

