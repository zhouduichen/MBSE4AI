from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_app_serves_resource_pages_and_local_assets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    response = client.get("/ui/projects")
    assert response.status_code == 200
    assert "项目" in response.text
    assert "MBSE 模型" in response.text
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert "--acc" in css.text
    htmx = client.get("/static/vendor/htmx.min.js")
    assert htmx.status_code == 200


def test_project_page_renders_shared_shell_and_delete_control(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.get("/ui/projects")

    assert response.status_code == 200
    assert 'class="app-shell"' in response.text
    assert 'delete-project' in response.text
    assert 'data-project-id="p1"' in response.text
    assert "/ui/projects/p1/engineering-flow" in response.text
    assert 'method: "DELETE"' in response.text


def test_project_page_has_create_entry_and_posts_to_project_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))

    response = client.get("/ui/projects")

    assert response.status_code == 200
    assert "创建项目" in response.text
    assert "本地工作区不是自动创建的项目" in response.text
    assert 'id="create-project-form"' in response.text
    assert 'fetch("/projects", {method: "POST"' in response.text


def test_engineering_flow_page_exposes_one_entry_product_chain(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.get("/ui/projects/p1/engineering-flow")

    assert response.status_code == 200
    assert "统一工程流" in response.text
    assert "运行统一工程流" in response.text
    assert "R → F → L → P → V&amp;V" in response.text
    assert "/projects/${encodeURIComponent(projectId)}/engineering-flow" in response.text
    assert "不会自动批准或执行下游工程变更" in response.text


def test_engineering_flow_page_lists_parsed_document_sources(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    uploaded = client.post(
        "/projects/p1/documents",
        files={"file": ("brief.txt", "系统应支持人工接管".encode(), "text/plain")},
    )
    document_id = uploaded.json()["document"]["document_id"]

    response = client.get("/ui/projects/p1/engineering-flow")

    assert response.status_code == 200
    assert document_id in response.text
    assert "1 个来源片段" in response.text
