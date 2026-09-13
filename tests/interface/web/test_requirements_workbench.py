from fastapi.testclient import TestClient

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.interface.web.app import create_app


def _client_with_fixture(tmp_path, runtime=None):
    app = create_app(tmp_path / "workspaces")
    if runtime is not None:
        app.state.container.v2._runtime_override = runtime
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    requirement = make_entity(EntityKind.REQUIREMENT, "Battery shall last 8 hours", {"statement": "Battery shall last 8 hours"})
    function = make_entity(EntityKind.FUNCTION, "Manage energy")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "Energy controller")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "Battery pack")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "Endurance test", {"method": "test", "pass_criteria": ">=8h"})
    validation = make_entity(EntityKind.VALIDATION_CASE, "Operational confirmation", {"method": "demonstration", "pass_criteria": "operator confirms"})
    relations = (Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id), Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id), Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id), Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id), Relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id))
    patch = Patch.create("p1", "fixture", (AddEntity(requirement), AddEntity(function), AddEntity(logical), AddEntity(physical), AddEntity(verification), AddEntity(validation), *relations), "fixture", 0)
    app.state.container.v2.repository("p1").append_patch("p1", patch, 0)
    return client, requirement.id


def test_requirements_workbench_routes_render_and_filter(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)
    response = client.get("/projects/p1/requirements", params={"q": "8 hours", "missing_trace": "true"})
    assert response.status_code == 200
    assert response.json()["filtered_count"] == 0
    detail = client.get(f"/projects/p1/requirements/{requirement_id}")
    assert detail.status_code == 200
    assert detail.json()["trace_path"][0] == requirement_id
    assert client.get("/ui/projects/p1/requirements").status_code == 200


def test_documents_page_lists_uploaded_project_inputs(tmp_path):
    app = create_app(tmp_path / "workspaces")
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    result = client.post("/projects/p1/documents", files={"file": ("requirements.txt", b"The system shall stop safely.", "text/plain")})
    assert result.status_code == 200

    page = client.get("/ui/projects/p1/documents")

    assert page.status_code == 200
    assert "requirements.txt" in page.text
    assert "打开 Analysis" in page.text
