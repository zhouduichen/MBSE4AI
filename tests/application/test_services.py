from pathlib import Path

from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_project_service_imports_fixture_and_keeps_typed_graph(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p1", "项目")
    result = services.projects.seed_fixture("p1", {
        "system": "系统", "stakeholders": ["用户"], "lifecycle_stages": ["运行"],
        "scenarios": ["正常"], "requirements": [{"id": "r1", "statement": "支持配送"}],
    })

    assert result["entity_count"] == 5
    graph = services.model("p1").graph("p1")
    assert any(item.kind is EntityKind.REQUIREMENT for item in graph.entities)
    assert next(item for item in graph.entities if item.kind is EntityKind.SYSTEM).payload == {}


def test_analysis_service_runs_offline_and_view_compiles_from_graph(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p1")
    services.projects.seed_fixture("p1", {"system": "系统", "stakeholders": ["用户"], "lifecycle_stages": ["运行"], "scenarios": ["正常"], "requirements": []})

    result = services.analysis("p1").run("p1")
    view = services.render("p1").view("p1", "operational")

    assert result.completed_tasks
    assert view.source_graph_hash
    assert view.nodes


def test_request_profile_overrides_active_profile_without_mutating_settings(tmp_path: Path):
    config_dir = tmp_path / "config"
    profiles = LLMProfileService(config_dir)
    profiles.save({
        "id": "active-profile",
        "label": "活动配置",
        "kind": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "test-local-model",
    })
    profiles.save({
        "id": "remote-profile",
        "label": "远程配置",
        "kind": "remote",
        "provider": "ollama",
        "base_url": "http://remote.example.invalid:11434/v1",
        "model": "qwen3.5:9b-q8_0",
    })
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
        config_dir=config_dir,
    )
    services.projects.create("robot")

    result = services.generation("robot", profile_id="remote-profile").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    run = services.repository("robot").load_run("robot", result.run_id)

    assert run is not None
    assert run.model_profile == "remote-profile"
    assert run.provider_id == "ollama"
    assert services.settings.list_profiles()["active_id"] == "active-profile"
