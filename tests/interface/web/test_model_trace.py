from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.interface.web.app import create_app


def test_model_trace_returns_clickable_rflp_verification_path(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    repository = client.app.state.container.v2.repository("p1")
    requirement = make_entity(EntityKind.REQUIREMENT, "Battery shall last 8 hours", {"statement": "Battery shall last 8 hours"})
    function = make_entity(EntityKind.FUNCTION, "Manage energy")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "Energy controller")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "Battery pack")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "Battery endurance test")
    graph = repository.load_graph("p1")
    operations = (
        AddEntity(requirement),
        AddEntity(function),
        AddEntity(logical),
        AddEntity(physical),
        AddEntity(verification),
        Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
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
    assert [node["stage"] for node in path["nodes"]] == payload["stages"]
    assert path["nodes"][0]["href"].endswith(f"#entity-{requirement.id}")

    page = client.get("/ui/projects/p1/model")
    assert page.status_code == 200
    assert "Requirement → Function → Logical → Physical → Verification" in page.text
    assert "Battery endurance test" in page.text
