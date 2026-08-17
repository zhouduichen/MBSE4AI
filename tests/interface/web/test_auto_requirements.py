from __future__ import annotations

from fastapi.testclient import TestClient

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.interface.web.app import create_app
from rflp_lite.ports.generative_model import GenerationResponse


class FixtureModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0
        self.requests = []

    def complete_json(self, request):
        self.calls += 1
        self.requests.append(request)
        return GenerationResponse(
            request.lens_id,
            self.payload,
            canonical_hash(request.user_payload),
            canonical_hash(self.payload),
            False,
        )


class FailingModel:
    def complete_json(self, _request):
        raise AdapterFailure("synthetic model failure")


def _payload() -> dict[str, object]:
    return {
        "system": {"name": "医用安全电动牙刷", "domain": "医疗器械", "mission": "安全清洁"},
        "stakeholders": [
            {"id": "user", "name": "牙刷使用者", "category": "end_user", "goals": ["安全清洁"]},
            {"id": "manufacturer", "name": "医疗器械制造商", "category": "supplier", "goals": ["稳定生产"]},
        ],
        "concerns": [
            {"id": "safety", "name": "口腔安全", "stakeholder_id": "user"},
        ],
        "needs": [
            {"id": "safe-use", "name": "安全使用", "statement": "使用者需要安全清洁", "stakeholder_id": "user", "concern_id": "safety"},
        ],
        "requirements": [
            {"id": "pressure-limit", "statement": "系统应限制刷牙压力", "subject": "系统", "predicate": "应", "source_type": "inferred"},
        ],
        "scenarios": [
            {"id": "normal-brushing", "title": "正常刷牙", "scenario_type": "normal", "actors": ["牙刷使用者"], "steps": ["启动", "刷牙"], "expected_outcomes": ["安全完成"], "requirement_ids": ["pressure-limit"]},
            {"id": "sensor-failure", "title": "压力传感器故障", "scenario_type": "failure", "actors": ["牙刷使用者"], "steps": ["检测故障", "降低输出"], "expected_outcomes": ["避免伤害"], "requirement_ids": ["pressure-limit"]},
        ],
        "architecture": {
            "functions": [{"id": "pressure-control", "name": "压力控制", "requirement_ids": ["pressure-limit"]}],
            "logical_components": [{"id": "control-logic", "name": "控制逻辑", "requirement_ids": ["pressure-limit"]}],
            "physical_components": [{"id": "pressure-sensor", "name": "压力传感器", "requirement_ids": ["pressure-limit"]}],
            "interfaces": [{"id": "pressure-feedback", "name": "压力反馈接口", "source_id": "pressure-sensor", "target_id": "control-logic"}],
            "relations": [],
        },
        "open_questions": ["目标压力范围是多少？"],
    }


def _client(tmp_path, monkeypatch, model) -> TestClient:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/workspaces", data={"name": "medical"}, follow_redirects=False).status_code == 303
    facade = client.app.state.facade
    monkeypatch.setattr(facade, "_project_analysis_model", lambda: model)
    return client


def test_submit_uses_one_current_domain_analysis_and_populates_modules(tmp_path, monkeypatch) -> None:
    model = FixtureModel(_payload())
    client = _client(tmp_path, monkeypatch, model)

    submitted = client.post(
        "/w/medical/requirements/analyze",
        data={"text": "设计一款医用安全电动牙刷"},
        follow_redirects=False,
    )

    assert submitted.status_code == 303
    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    assert model.calls == 1
    assert {item["name"] for item in state["stakeholders"]} == {"牙刷使用者", "医疗器械制造商"}
    assert {item["title"] for item in state["scenarios"]} == {"正常刷牙", "压力传感器故障"}
    assert state["auto_analysis"]["status"] == "completed"
    assert state["rflp"]
    assert state["rflp"]["metrics"]["interfaces"] == 1
    assert state["rflp"]["metrics"]["relations"] >= 4
    assert state["mbse"]
    assert "飞行员" not in str(state)
    assert "urban-medical-aam-v1" not in str(state)

    input_page = client.get("/w/medical/requirements/input")
    assert "自动分析已完成" in input_page.text
    assert "本次项目输入已生成利益相关方、需求检查、场景、RFLP 和 MBSE 结果" in input_page.text


def test_submit_waits_without_llm_and_does_not_inject_domain_fallback(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, FailingModel())

    submitted = client.post(
        "/w/medical/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
        follow_redirects=False,
    )

    assert submitted.status_code == 303
    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    assert state["claims"]
    assert state["rflp"] is None
    assert state["mbse"] is None
    assert state["scenarios"] == []
    assert state["auto_analysis"]["status"] == "waiting_for_llm"
    assert "飞行汽车" not in str(state)


def test_two_projects_keep_their_llm_entities_and_links_separate(tmp_path, monkeypatch) -> None:
    class RoutingModel:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete_json(self, request):
            workspace = request.user_payload["project_scope"]["workspace"]
            self.calls.append(workspace)
            payload = _payload()
            if workspace == "aircar":
                payload["system"] = {"name": "医疗飞行汽车", "domain": "航空器", "mission": "医疗转运"}
                payload["stakeholders"] = [{"id": "pilot", "name": "飞行员", "category": "operator", "goals": ["安全飞行"]}]
                payload["scenarios"] = [{"id": "flight", "title": "医疗转运", "scenario_type": "normal", "actors": ["飞行员"], "steps": ["起飞", "转运"], "expected_outcomes": ["完成转运"], "requirement_ids": ["pressure-limit"]}]
            else:
                payload["system"] = {"name": "医用安全电动牙刷", "domain": "医疗器械", "mission": "安全清洁"}
            return GenerationResponse(
                request.lens_id,
                payload,
                canonical_hash(request.user_payload),
                canonical_hash(payload),
                False,
            )

    from rflp_lite.application.web_facade import WebFacade

    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("aircar")
    facade.create_workspace("toothbrush")
    model = RoutingModel()
    monkeypatch.setattr(facade, "_project_analysis_model", lambda: model)

    facade.analyze_requirements("aircar", "requirements.txt", "设计医疗飞行汽车".encode(), merge=False)
    facade.analyze_requirements("toothbrush", "requirements.txt", "设计医用安全电动牙刷".encode(), merge=False)

    aircar = facade.requirements("aircar")
    toothbrush = facade.requirements("toothbrush")
    assert {item["name"] for item in aircar["stakeholders"]} == {"飞行员"}
    assert {item["name"] for item in toothbrush["stakeholders"]} == {"牙刷使用者", "医疗器械制造商"}
    assert "飞行员" not in str(toothbrush)
    assert "牙刷使用者" not in str(aircar)
    assert model.calls == ["aircar", "toothbrush"]


def test_analysis_config_defaults_to_neutral_and_can_enable_common_pack(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, FailingModel())
    client.post(
        "/w/medical/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
        follow_redirects=False,
    )

    default = client.get(
        "/api/v1/workspaces/medical/requirements/analysis-config"
    )
    assert default.status_code == 200
    assert default.json()["config"]["enabled"] is False
    assert default.json()["config"]["domain_pack_id"] is None
    assert [item["id"] for item in default.json()["available_domain_packs"]] == [
        "common-v1"
    ]

    configured = client.put(
        "/api/v1/workspaces/medical/requirements/analysis-config",
        json={
            "enabled": True,
            "domain_pack_id": "common-v1",
            "domain_pack_version": 1,
        },
    )
    assert configured.status_code == 200
    assert configured.json()["config"]["domain_pack_id"] == "common-v1"

    invalid = client.put(
        "/api/v1/workspaces/medical/requirements/analysis-config",
        json={
            "enabled": True,
            "domain_pack_id": "urban-medical-aam-v1",
            "domain_pack_version": 1,
        },
    )
    assert invalid.status_code == 422
    assert "常见领域包" in invalid.json()["message"]


def test_common_pack_guidance_is_loaded_only_after_explicit_configuration(
    tmp_path, monkeypatch
) -> None:
    model = FixtureModel(_payload())
    client = _client(tmp_path, monkeypatch, model)
    client.post(
        "/w/medical/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
        follow_redirects=False,
    )
    assert "domain_guidance" not in model.requests[0].user_payload

    configured = client.put(
        "/api/v1/workspaces/medical/requirements/analysis-config",
        json={"enabled": True, "domain_pack_id": "common-v1", "domain_pack_version": 1},
    )
    assert configured.status_code == 200
    client.post(
        "/w/medical/requirements/analyze",
        data={"text": "审计人员必须查看恢复记录。"},
        follow_redirects=False,
    )

    assert model.calls == 2
    assert model.requests[1].user_payload["domain_guidance"]["id"] == "common-v1"
    assert model.requests[1].user_payload["domain_guidance"]["coverage_rules"]
