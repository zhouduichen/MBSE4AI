import json
from pathlib import Path

from scripts.architecture_metrics import measure


def test_budget_is_json_and_matches_current_tree() -> None:
    budget = json.loads(Path("architecture_budget.json").read_text(encoding="utf-8"))
    actual = measure()
    assert set(actual) <= set(budget)
    for key, value in actual.items():
        assert value <= budget[key], f"architecture budget increased: {key}={value} > {budget[key]}"


def test_legacy_core_clusters_are_removed() -> None:
    source = Path("src/rflp_lite")
    forbidden = (
        source / "application" / "intelligence",
        source / "application" / "mbse",
        source / "application" / "web_facade.py",
        source / "adapters" / "sqlite_repository.py",
        source / "simulation",
    )
    remaining = [
        str(path)
        for path in forbidden
        if path.is_file() or (path.is_dir() and any(path.rglob("*.py")))
    ]
    assert remaining == []
