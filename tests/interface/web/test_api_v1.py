from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rflp_lite.adapters import llm_client
from rflp_lite.interface.web.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RFLP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    return TestClient(create_app(tmp_path / "workspaces"))


def _workbench(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    response = client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_api_v1_reads_and_executes_local_scenario(client: TestClient) -> None:
    _workbench(client)

    created = client.post(
        "/api/v1/workspaces/demo/scenarios",
        json={
            "title": "恢复版本",
            "description": "验证恢复流程",
            "steps": ["选择版本", "确认恢复"],
            "expected_outcomes": ["内容恢复"],
        },
    )
    assert created.status_code == 200
    scenario_id = created.json()["scenario"]["id"]

    listed = client.get("/api/v1/workspaces/demo/scenarios")
    assert listed.status_code == 200
    assert listed.json()["scenarios"][0]["id"] == scenario_id

    executed = client.post(f"/api/v1/workspaces/demo/scenarios/{scenario_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "ok"
    execution = body["execution"]
    assert execution["status"] == "completed"
    assert execution["verification"] == "declarative-only"

    job_id = execution["job"]["id"]
    job = client.get(f"/api/v1/workspaces/demo/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["job"]["status"] == "succeeded"


def test_api_v1_profile_and_error_contract(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})

    profile = client.get("/api/v1/workspaces/demo/profile")
    assert profile.status_code == 200
    updated = client.put(
        "/api/v1/workspaces/demo/profile",
        json={
            "name": "local-editor",
            "solver": "heuristic",
            "seed": 8,
            "candidate_limit": 2,
            "timeout_seconds": 10,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["profile"]["name"] == "local-editor"

    missing = client.get("/api/v1/workspaces/missing/profile")
    assert missing.status_code == 404
    assert missing.json()["status"] == "failed"


def test_api_v1_exposes_local_plugin_registry(client: TestClient) -> None:
    plugins = client.get("/api/v1/plugins")

    assert plugins.status_code == 200
    assert plugins.json()["plugins"][0]["name"] == "scenario-trace"

    missing = client.post("/api/v1/plugins/missing", json={})
    assert missing.status_code == 422
    assert missing.json()["status"] == "failed"


def test_api_v1_configures_generic_llm_profiles_without_leaking_key(client: TestClient) -> None:
    presets = client.get("/api/v1/llm/presets")
    assert presets.status_code == 200
    assert presets.json()["presets"]["deepseek"]["protocol"] == "openai-chat"
    assert presets.json()["presets"]["qwen"]["base_url"]

    saved = client.post(
        "/api/v1/llm/profiles",
        json={
            "id": "qwen-main",
            "label": "千问主模型",
            "kind": "remote",
            "protocol": "openai-chat",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
            "api_key": "secret-key",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["profile"]["api_key_configured"] is True
    assert "secret-key" not in saved.text

    listed = client.get("/api/v1/llm/profiles")
    assert listed.status_code == 200
    assert listed.json()["active_id"] == "qwen-main"
    assert listed.json()["profiles"][0]["label"] == "千问主模型"


def test_llm_settings_page_is_available(client: TestClient) -> None:
    response = client.get("/settings/llm")
    assert response.status_code == 200
    assert "LLM 连接" in response.text
    assert "DeepSeek" in response.text
    assert "通义千问" in response.text


def test_active_local_llm_profile_drives_workbench_ai_analysis(client: TestClient, monkeypatch) -> None:
    _workbench(client)
    state = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    span_id = state["spans"][0]["id"]
    client.post(
        "/api/v1/llm/profiles",
        json={
            "id": "local-model",
            "label": "本地模型",
            "kind": "local",
            "protocol": "openai-chat",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen-local",
        },
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    [
                                        {
                                            "stakeholder": "审计人员",
                                            "concern": "审计",
                                            "need": "保留可追溯记录",
                                            "source_span_id": span_id,
                                        }
                                    ],
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode()

    monkeypatch.setattr(llm_client.request, "urlopen", lambda *_args, **_kwargs: Response())
    analyzed = client.post("/w/demo/requirements/ai", follow_redirects=False)
    assert analyzed.status_code == 303
    updated = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    assert any(item["producer"] == "llm" for item in updated["stakeholders"])


def test_api_v1_exports_and_imports_sysml_v2_subset(client: TestClient) -> None:
    _workbench(client)
    client.post("/w/demo/requirements/accept-traceable")
    generated = client.post("/w/demo/requirements/generate")
    assert generated.status_code == 200

    exported = client.get("/api/v1/workspaces/demo/rflp.sysml")
    assert exported.status_code == 200
    assert "package RFLP_Lite" in exported.text

    imported = client.put(
        "/api/v1/workspaces/demo/rflp.sysml",
        content=exported.content,
        headers={"content-type": "text/plain"},
    )
    assert imported.status_code == 200
    assert imported.json()["rflp"]["elements"]


def test_api_v1_mlflow_endpoint_reports_real_or_missing_sdk(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    started = client.post(
        "/w/demo/runs",
        data={"solver": "heuristic", "seed": "42"},
        follow_redirects=False,
    )
    result_hash = started.headers["location"].rsplit("/", 1)[-1]

    response = client.post(
        f"/api/v1/workspaces/demo/runs/{result_hash}/mlflow", json={}
    )

    assert response.status_code == 200
    assert response.json()["status"] in {"tracked", "not_configured"}
