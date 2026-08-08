from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "versioned-content-service"

REQUIREMENTS = (
    "管理员必须恢复历史版本。\n"
    "The service shall restore a historical version.\n"
    "The service must record an audit event for every restore.\n"
    "审计人员必须查看恢复记录。"
)

DOWNLOADS = (
    "project.json",
    "baseline.json",
    "actual-model.json",
    "matches.json",
    "delta.json",
    "task-contracts.json",
    "evidence.json",
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "workspaces"))


def _prepare_workbench(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post("/w/demo/requirements/analyze", data={"text": REQUIREMENTS})
    client.post("/w/demo/requirements/accept-traceable")
    client.post("/w/demo/requirements/generate")


def test_project_page_guides_when_workbench_empty(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    response = client.get("/w/demo/project")
    assert response.status_code == 200
    assert "先建立需求模型" in response.text


def test_approve_requires_generated_rflp(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post("/w/demo/requirements/analyze", data={"text": REQUIREMENTS})
    response = client.post("/w/demo/project/approve-baseline")
    assert response.status_code == 422
    assert "请先生成 RFLP 规划图" in response.text


def test_full_project_flow(client: TestClient) -> None:
    _prepare_workbench(client)

    page = client.get("/w/demo/project")
    assert "人工批准基线" in page.text
    assert "待批准" in page.text

    assert client.post(
        "/w/demo/project/approve-baseline", follow_redirects=False
    ).status_code == 303
    page = client.get("/w/demo/project")
    assert "已批准" in page.text
    assert "连接本地 Python 项目" in page.text

    assert client.post(
        "/w/demo/project/analyze",
        data={"source": str(EXAMPLE)},
        follow_redirects=False,
    ).status_code == 303
    page = client.get("/w/demo/project")
    assert "MISSING" in page.text
    assert "任务契约" in page.text
    assert "基线 → 实际匹配" in page.text

    for filename in DOWNLOADS:
        response = client.get(f"/w/demo/project/download/{filename}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    assert client.get("/w/demo/project/download/not-registered.json").status_code == 404
    assert client.get("/w/demo/project/download/../../baseline.json").status_code == 404


def test_analyze_requires_approved_baseline(client: TestClient) -> None:
    _prepare_workbench(client)
    response = client.post("/w/demo/project/analyze", data={"source": str(EXAMPLE)})
    assert response.status_code == 422
    assert "请先批准基线" in response.text


def test_verify_requires_approved_baseline(client: TestClient) -> None:
    _prepare_workbench(client)
    response = client.post(
        "/w/demo/project/verify", data={"source": str(EXAMPLE)}
    )
    assert response.status_code == 422
    assert "请先批准基线" in response.text


def test_verify_after_analyze_shows_execution_panel(client: TestClient) -> None:
    _prepare_workbench(client)
    client.post("/w/demo/project/approve-baseline")
    client.post("/w/demo/project/analyze", data={"source": str(EXAMPLE)})
    assert client.post(
        "/w/demo/project/verify",
        data={"source": str(EXAMPLE)},
        follow_redirects=False,
    ).status_code == 303

    page = client.get("/w/demo/project").text
    assert "任务契约执行验证" in page
    assert "执行验证" in page


def test_test_requires_analyzed_project(client: TestClient) -> None:
    _prepare_workbench(client)
    response = client.post("/w/demo/project/test")
    assert response.status_code == 422
    assert "请先在项目接入中分析项目" in response.text


def test_analyze_merge_accumulates_candidates(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze", data={"text": "管理员必须恢复历史版本。\n"}
    )
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "审计人员必须查看恢复记录。\n", "merge": "on"},
    )
    page = client.get("/w/demo/requirements").text
    assert "管理员" in page
    assert "审计人员" in page


def test_test_runs_pytest_on_project(client: TestClient, tmp_path: Path) -> None:
    _prepare_workbench(client)
    client.post("/w/demo/project/approve-baseline")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    client.post("/w/demo/project/analyze", data={"source": str(project)})

    assert client.post("/w/demo/project/test", follow_redirects=False).status_code == 303

    page = client.get("/w/demo/project").text
    assert "运行项目测试" in page
    assert "测试证据" in page


def test_test_runs_unittest_with_controls(client: TestClient, tmp_path: Path) -> None:
    _prepare_workbench(client)
    client.post("/w/demo/project/approve-baseline")
    project = tmp_path / "unittest-project"
    project.mkdir()
    (project / "test_case.py").write_text(
        "import unittest\n\n"
        "class Case(unittest.TestCase):\n"
        "    def test_passes(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    client.post("/w/demo/project/analyze", data={"source": str(project)})

    response = client.post(
        "/w/demo/project/test",
        data={
            "runner": "unittest",
            "timeout": "120",
            "memory_mib": "0",
            "max_open_files": "0",
            "output_mib": "1",
            "jobs": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/w/demo/project").text
    assert "unittest" in page
    assert "cache=" in page


def test_test_rejects_unknown_runner(client: TestClient, tmp_path: Path) -> None:
    _prepare_workbench(client)
    client.post("/w/demo/project/approve-baseline")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    client.post("/w/demo/project/analyze", data={"source": str(project)})
    response = client.post("/w/demo/project/test", data={"runner": "shell"})
    assert response.status_code == 422
    assert "测试运行器只能是 pytest 或 unittest" in response.text


def test_analyze_is_deterministic_across_runs(client: TestClient) -> None:
    _prepare_workbench(client)
    client.post("/w/demo/project/approve-baseline")
    client.post("/w/demo/project/analyze", data={"source": str(EXAMPLE)})
    first = client.get("/w/demo/project/download/project.json").text
    client.post("/w/demo/project/analyze", data={"source": str(EXAMPLE)})
    second = client.get("/w/demo/project/download/project.json").text
    assert first == second


def test_approve_and_analyze_record_audit_events(
    client: TestClient, tmp_path: Path
) -> None:
    _prepare_workbench(client)
    client.post("/w/demo/project/approve-baseline")
    client.post("/w/demo/project/analyze", data={"source": str(EXAMPLE)})

    from rflp_lite.adapters.sqlite_repository import SQLiteRepository

    repository = SQLiteRepository(tmp_path / "workspaces" / "demo" / ".rflp" / "model.db")
    try:
        kinds = [event["kind"] for event in repository.audit_events()]
        assert "baseline.approved" in kinds
        assert "project.analyzed" in kinds
        assert "requirements.accepted" in kinds
    finally:
        repository.close()
