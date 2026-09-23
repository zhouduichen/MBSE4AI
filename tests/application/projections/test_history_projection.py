from pathlib import Path

from rflp_lite.application.projections.history import build_history_view, build_revision_diff
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.repository.sqlite import SQLiteModelRepository


def test_history_and_diff_read_repository_revisions(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    entity = make_entity(EntityKind.REQUIREMENT, "R")
    repository.append_patch("p1", Patch.create("p1", "fixture", (AddEntity(entity),), "seed", 0), 0)
    history = build_history_view(repository, "p1")
    assert history["metrics"] == {"revision_count": 1, "run_count": 0, "patch_count": 1}
    diff = build_revision_diff(None, repository.load_revision("p1", 1), revision=1)
    assert [item["id"] for item in diff["added_entities"]] == [entity.id]
    assert diff["change_count"] == 1
