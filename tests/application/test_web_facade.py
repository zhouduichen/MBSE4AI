from pathlib import Path

from rflp_lite.application.web_facade import WebFacade


def test_empty_dashboard_is_honest(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    view = facade.dashboard(None)
    assert view["workspace"] is None
    assert view["latest_run"] is None
    assert view["counts"] == {}


def test_facade_creates_workspace_and_executes_both_solvers(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("demo")
    heuristic = facade.execute("demo", "heuristic", 42)
    cp_sat = facade.execute("demo", "cp-sat", 42)
    assert heuristic.manifest["status"] == "passed"
    assert cp_sat.manifest["status"] == "passed"
    assert heuristic.result_hash != cp_sat.result_hash
    assert heuristic.manifest["baseline_hash"] == cp_sat.manifest["baseline_hash"]
