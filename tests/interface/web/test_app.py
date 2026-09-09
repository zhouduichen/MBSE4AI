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
    assert 'method: "DELETE"' in response.text


def test_project_page_has_create_entry_and_posts_to_project_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))

    response = client.get("/ui/projects")

    assert response.status_code == 200
    assert "创建项目" in response.text
    assert "本地工作区不是自动创建的项目" in response.text
    assert 'id="create-project-form"' in response.text
    assert 'fetch("/projects", {method: "POST"' in response.text
