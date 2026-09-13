from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.interface.web.app import create_app


def test_model_trace_returns_clickable_rflp_verification_path(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    repository = client.app.state.container.v2.repository("p1")
    requirement = make_entity(EntityKind.REQUIREMENT, "Battery shall last 8 hours", {"statement": "Battery shall last 8 hours", "obligation": "电池应持续 8 小时"}, status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "Manage energy")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "Energy controller")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "Battery pack")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "Battery endurance test")
    validation = make_entity(EntityKind.VALIDATION_CASE, "Operator confirmation")
    graph = repository.load_graph("p1")
    operations = (
        AddEntity(requirement),
        AddEntity(function),
        AddEntity(logical),
        AddEntity(physical),
        AddEntity(verification),
        AddEntity(validation),
        Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    )
    repository.append_patch("p1", Patch.create("p1", "test.trace", operations, "seed trace", graph.revision), graph.revision)

    response = client.get("/projects/p1/trace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 1
    assert payload["stages"] == [
        "Requirement",
        "Function",
        "Logical",
        "Physical",
        "Verification",
    ]
    path = payload["paths"][0]
    assert path["complete"] is True
    assert path["validation"]["id"] == validation.id
    assert [node["stage"] for node in path["nodes"]] == payload["stages"]
    assert path["nodes"][0]["href"].endswith(f"#entity-{requirement.id}")

    coverage = client.get("/projects/p1/coverage")
    assert coverage.status_code == 200
    assert coverage.json()["metrics"]["requirement_count"] == 1
    assert coverage.json()["rows"][0]["paths"] == [[requirement.id, function.id, logical.id, physical.id]]

    page = client.get("/ui/projects/p1/model")
    assert page.status_code == 200
    assert "需求 → 功能 → 逻辑 → 物理 → 验证" in page.text
    assert "Battery endurance test" in page.text
    assert "Operator confirmation" in page.text
