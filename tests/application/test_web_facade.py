from pathlib import Path

from rflp_lite.application.web_facade import WebFacade


def test_empty_dashboard_is_honest(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    view = facade.dashboard(None)
    assert view["workspace"] is None
    assert view["latest_run"] is None
    assert view["counts"] == {}

