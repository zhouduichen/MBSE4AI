from __future__ import annotations

from rflp_lite.application.queries import (
    MBSEView,
    RequirementsPageView,
    WorkspaceView,
    mbse_view,
    requirements_page_view,
    workspace_view,
)


def test_query_views_are_immutable_and_keep_legacy_fields() -> None:
    state = {
        "revision": 4,
        "content_revision": 2,
        "claims": [
            {"id": "req-1", "object": "系统应安全", "status": "accepted"},
            {"id": "req-2", "object": "系统应可追溯", "status": "candidate"},
        ],
        "rflp": {"elements": []},
        "mbse": {"status": "accepted", "revision": "mbse-1", "semantic_model": {"relations": []}},
    }
    requirements = requirements_page_view(
        state,
        tuple(state["claims"]),
        workspace="demo",
    )
    workspace = workspace_view("demo", "/tmp/demo", state)
    mbse = mbse_view(state, ({"id": "rflp"},))

    assert isinstance(requirements, RequirementsPageView)
    assert requirements.as_dict()["counts"] == {"candidate": 1, "accepted": 1, "rejected": 0}
    assert requirements.items[0].id == "req-1"
    assert isinstance(workspace, WorkspaceView)
    assert workspace.accepted_requirement_count == 1
    assert isinstance(mbse, MBSEView)
    assert mbse.view_count == 1
