import json
from pathlib import Path

from scripts.architecture_metrics import measure


def test_budget_is_json_and_matches_current_tree() -> None:
    budget = json.loads(Path("architecture_budget.json").read_text(encoding="utf-8"))
    actual = measure()
    assert set(actual) <= set(budget)
    for key, value in actual.items():
        assert value <= budget[key], f"architecture budget increased: {key}={value} > {budget[key]}"
