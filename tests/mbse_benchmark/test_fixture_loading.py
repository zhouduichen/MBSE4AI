from __future__ import annotations

from pathlib import Path

from tests.mbse_benchmark.cases.loader import load_cases, load_expectations


ROOT = Path(__file__).parent


def test_all_five_cases_and_expectations_load() -> None:
    cases = load_cases(ROOT / "cases")
    expectations = load_expectations(ROOT / "expected")

    assert [case["case_id"] for case in cases] == [
        "CASE-01", "CASE-02", "CASE-03", "CASE-04", "CASE-05"
    ]
    assert expectations["metric_targets"]["known_conflict_detection"] == 1.0


def test_fault_injection_case_keeps_the_task_book_numbers() -> None:
    case = next(case for case in load_cases(ROOT / "cases") if case["case_id"] == "CASE-05")

    assert [item["mass"] for item in case["physical_design"]] == [15, 8, 4, 3, 2]
    assert case["power_budget"] == {"average_power": 200, "power_unit": "W"}
    assert case["requirements"][0]["metric"] == {
        "name": "mass", "operator": "<=", "value": 20, "unit": "kg"
    }
    assert case["requirements"][1]["metric"] == {
        "name": "runtime", "operator": ">=", "value": 12, "unit": "h"
    }
