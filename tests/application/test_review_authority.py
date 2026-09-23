from rflp_lite.application.model_service import ModelService
from rflp_lite.application.review_service import ReviewService
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.repository.sqlite import SQLiteModelRepository


def _service(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    entity = make_entity(
        EntityKind.REQUIREMENT,
        "电池续航需求",
        {"statement": "续航不少于 10 小时", "obligation": "续航不少于 10 小时"},
        status=EntityStatus.CANDIDATE,
    )
    repository.append_patch(
        "p1",
        Patch.create("p1", "seed", (AddEntity(entity),), "seed", 0),
        0,
    )
    return repository, entity.id, ReviewService(ModelService(repository))


def test_review_accept_edit_and_audit_are_the_manual_authority(tmp_path):
    repository, entity_id, service = _service(tmp_path)

    accepted = service.accept_entity("p1", entity_id, expected_revision=1)
    edited = service.edit_entity(
        "p1",
        entity_id,
        statement="续航不少于 12 小时",
        expected_revision=accepted.revision["sequence"],
    )
    current = repository.load_graph("p1").entity_index[entity_id]

    assert edited.status == EntityStatus.CANDIDATE.value
    assert current.meta.status is EntityStatus.CANDIDATE
    assert current.meta.producer is Producer.USER
    assert current.payload["trace_status"] == "stale"
    assert current.payload["user_modified"] is True
    assert any(item["kind"] == "review.edit" for item in repository.list_audit_events("p1"))

