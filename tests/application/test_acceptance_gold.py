import pytest

from rflp_lite.application.acceptance_gold import (
    match_requirement_items,
    validate_gold_payload,
)
from rflp_lite.domain.errors import ContractViolation


def test_source_region_id_is_not_a_cross_run_identity():
    gold = validate_gold_payload({
        "version": 3,
        "corpus_mode": "complete",
        "details_mode": "complete",
        "requirements": [{
            "key": "REQ-1",
            "statement": "系统支持导入 PDF",
            "source_anchor": "支持导入 PDF",
            "details": [],
        }],
    })
    report = match_requirement_items(
        ({"id": "actual-1", "statement": "系统支持导入 PDF", "source_region_id": "region-new"},),
        gold.requirements,
        {"region-new": "第 1 条：支持导入 PDF。"},
    )
    assert report.matched == ("REQ-1",)
    assert report.provenance_complete == 100


def test_same_anchor_with_wrong_statement_is_not_a_match():
    gold = validate_gold_payload({
        "version": 3,
        "corpus_mode": "complete",
        "details_mode": "complete",
        "requirements": [{
            "key": "REQ-1",
            "statement": "系统支持导入 PDF",
            "source_anchor": "支持导入 PDF",
            "details": [],
        }],
    })
    report = match_requirement_items(
        ({"id": "actual-1", "statement": "系统删除全部数据", "source_region_id": "region-new"},),
        gold.requirements,
        {"region-new": "第 1 条：支持导入 PDF。"},
    )
    assert report.matched == ()
    assert report.unmatched_actual


def test_gold_rejects_duplicate_keys_and_non_complete_corpus():
    with pytest.raises(ContractViolation):
        validate_gold_payload({"version": 3, "corpus_mode": "sample", "details_mode": "complete", "requirements": []})
    with pytest.raises(ContractViolation):
        validate_gold_payload({
            "version": 3,
            "corpus_mode": "complete",
            "details_mode": "complete",
            "requirements": [
                {"key": "REQ-1", "statement": "A", "source_anchor": "A", "details": []},
                {"key": "REQ-1", "statement": "B", "source_anchor": "B", "details": []},
            ],
        })
