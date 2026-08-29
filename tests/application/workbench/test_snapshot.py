from __future__ import annotations

from rflp_lite.application.workbench.snapshot import WorkbenchSnapshot


def test_snapshot_is_read_only_and_working_copy_is_independent() -> None:
    source = {"revision": 4, "content_revision": 2, "items": [{"id": "one"}]}
    snapshot = WorkbenchSnapshot.from_state("demo", source)

    assert snapshot.revision == 4
    assert snapshot.content_revision == 2
    assert snapshot.input_hash
    copy = snapshot.working_copy()
    copy["items"][0]["id"] = "changed"

    assert snapshot.state["items"][0]["id"] == "one"
