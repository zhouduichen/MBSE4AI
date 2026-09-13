from __future__ import annotations

from tests.mbse_benchmark.cases.loader import load_cases, load_expectations
from tests.mbse_benchmark.validators.architecture import validate_architecture
from tests.mbse_benchmark.validators.common import validate_structural_graph
from tests.mbse_benchmark.validators.consistency import validate_consistency
from tests.mbse_benchmark.validators.regression import validate_regression
from tests.mbse_benchmark.validators.requirements import validate_requirements


def test_structural_validator_detects_missing_relation_endpoint() -> None:
    findings = validate_structural_graph({
        "project_id": "p1",
        "entities": [{"id": "req-1", "kind": "requirement", "name": "R1"}],
        "relations": [{"id": "rel-1", "source_id": "req-1", "predicate": "verifiedBy", "target_id": "tc-1"}],
    })

    assert any(item["category"] == "broken_reference" for item in findings)


def test_requirement_quality_counts_numeric_verification_and_source() -> None:
    result = validate_requirements({
        "project_id": "p1",
        "entities": [{
            "id": "req-1",
            "kind": "requirement",
            "name": "车辆运行时间不少于 12 小时",
            "status": "accepted",
            "source_ids": ["scenario-1"],
            "payload": {"statement": "车辆运行时间不少于 12 小时", "verification_method": "test"},
        }],
        "relations": [],
    })

    assert result["requirement_validity"] == 1.0
    assert result["requirement_verifiability"] == 1.0


def test_case05_validator_computes_both_known_conflicts_and_requires_signal() -> None:
    case = next(case for case in load_cases(__import__("pathlib").Path(__file__).parent / "cases") if case["case_id"] == "CASE-05")
    expectations = load_expectations(__import__("pathlib").Path(__file__).parent / "expected")
    graph = {
        "project_id": "case-05",
        "entities": [
            {"id": "req-weight", "kind": "requirement", "name": "重量", "status": "accepted", "payload": {}},
            {"id": "req-runtime", "kind": "requirement", "name": "续航", "status": "accepted", "payload": {}},
            {"id": "phy", "kind": "physical_block", "name": "电池", "status": "accepted", "payload": {}},
        ],
        "relations": [],
    }
    raw = {"graph": graph, "issues": [], "run_summary": {}, "audit": {}}
    result = validate_consistency(case, graph, raw, expectations)

    assert result["known_conflict_detection"] == 0.0
    assert result["false_satisfaction_signal"] is True


def test_orphan_rate_and_regression_are_deterministic() -> None:
    graph = {
        "project_id": "p1",
        "entities": [{"id": "system-1", "kind": "system", "name": "System"}],
        "relations": [],
    }
    architecture = validate_architecture(graph, {"case_id": "CASE-01"})
    result = {"case_id": "CASE-01", "graph": graph, "execution": {"status": "completed"}}
    regression = validate_regression([result, result, result], "CASE-01")

    assert architecture["orphan_element_rate"] == 0.0
    assert regression["regression_stability"] == 1.0
