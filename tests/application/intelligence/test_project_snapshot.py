from rflp_lite.application.intelligence.project_snapshot import (
    build_project_snapshot,
    source_batches,
)


def test_snapshot_batches_every_source_without_truncation() -> None:
    regions = [{"id": f"region-{index}", "text": f"需求 {index}"} for index in range(55)]
    state = {
        "revision": 8,
        "project_scope": {"workspace": "demo", "input_hash": "hash"},
        "document_regions": regions,
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "claims": [],
        "structured_requirements": [],
        "scenarios": [],
        "deletion_registry": [],
    }
    snapshot = build_project_snapshot(state, mode="full_reanalysis")
    batches = source_batches(snapshot, batch_size=20)
    assert [len(batch) for batch in batches] == [20, 20, 15]
    assert {item["id"] for batch in batches for item in batch} == {
        item["id"] for item in regions
    }


def test_empty_snapshot_still_has_one_batch() -> None:
    snapshot = build_project_snapshot({}, mode="incremental")
    assert source_batches(snapshot) == ((),)
