from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.application.sysml_v2 import graph_to_sysml
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.interface.web.app import create_app
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_resource_api_project_model_and_cas_patch(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.get("/projects/p1/model").json()["revision"] == 0
    response = client.patch("/projects/p1/entities/missing", json={"expected_revision": 0, "field_patch": {"name": "x"}})
    assert response.status_code == 422


def test_resource_api_can_delete_a_project_and_returns_404_afterward(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.delete("/projects/p1")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "project_id": "p1"}
    missing = client.delete("/projects/p1")
    assert missing.status_code == 404
    assert missing.json()["error"] == "NotFoundError"


def test_root_redirects_to_projects_and_requirement_intake_is_visible_in_model(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post("/projects/p1/requirements", json={"text": "系统应支持人工接管"})

    assert response.status_code == 200
    requirement = response.json()["requirement"]
    assert requirement["producer"] == "user"
    assert client.get("/projects/p1/model").json()["revision"] == 1


def test_project_goal_is_exposed_and_can_start_generation(tmp_path: Path):
    app = create_app(tmp_path)
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post("/projects/p1/goal", json={"goal": "建设可验证的校园配送系统"})
    assert response.status_code == 200
    assert response.json()["context"]["requirement"]["payload"]["source"] == "user_goal"
    context = client.get("/projects/p1/context")
    assert context.status_code == 200
    assert context.json()["context"]["goal"] == "建设可验证的校园配送系统"

    run = client.post("/projects/p1/analysis", json={"mode": "generate"})
    assert run.status_code == 200
    assert run.json()["run"]["mode"] == "generate"


def test_multipart_document_intake_is_saved(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/documents",
        files={"file": ("requirements.txt", "系统应支持人工接管\n", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["document"]["region_count"] == 1


def test_sysml_model_export_is_available_from_web_api(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post("/projects/p1/requirements", json={"text": "系统应支持人工接管"}).status_code == 200

    response = client.post("/projects/p1/export", json={"view_id": "rflp", "format": "sysml"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "package AI4MBSE_Model" in response.text


def test_empty_project_analysis_is_rejected_without_writing_a_run(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post("/projects/p1/analysis", json={"mode": "pipeline"})

    assert response.status_code == 422
    assert response.json()["error"] == "InputRequired"
    assert client.get("/projects/p1/model").json()["revision"] == 0


def test_partial_sysml_model_can_start_analysis_without_requirement_text(tmp_path: Path):
    app = create_app(tmp_path)
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    source_entity = make_entity(
        EntityKind.FUNCTION,
        "已有配送功能",
        {"behavior": "完成配送"},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
    )
    source = graph_to_sysml(
        ModelGraph(
            "source",
            (source_entity,),
            (),
            0,
        )
    )
    imported = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("partial.sysml", source, "text/plain")},
    )
    assert imported.status_code == 200

    response = client.post("/projects/p1/analysis", json={"mode": "generate"})

    assert response.status_code == 200
    assert response.json()["run"]["mode"] == "generate"
    model = client.get("/projects/p1/model").json()
    assert sum(item["kind"] == "requirement" for item in model["entities"]) == 1
    assert sum(item["kind"] == "function" for item in model["entities"]) == 1
    assert any(item["kind"] == "physical_block" for item in model["entities"])
    function = next(item for item in model["entities"] if item["kind"] == "function")
    assert function["id"] == source_entity.id
    assert function["name"] == "已有配送功能"
    requirement = next(item for item in model["entities"] if item["kind"] == "requirement")
    assert any(
        relation["source_id"] == requirement["id"]
        and relation["predicate"] == RelationPredicate.SATISFIED_BY.value
        and relation["target_id"] == source_entity.id
        for relation in model["relations"]
    )
    assert response.json()["run"]["traceability"]["complete_count"] == 1
