from pathlib import Path
from types import SimpleNamespace

from rflp_lite.application.input_preparation import InputPreparationService
from rflp_lite.domain.entities import EntityKind
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.runtime.rule_based import RuleRuntime


def test_offline_input_preparation_compiles_behavior_framework(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")

    result = InputPreparationService(
        repository,
        RuleRuntime(),
        audit_kind="test.input_preparation",
    ).prepare(
        "p1",
        requirement_text="操作员应在 2 秒内接收告警；系统应支持人工接管",
    )
    graph = repository.load_graph("p1")

    assert result.mode == "structured_intake"
    assert result.status == "degraded"
    assert any(item.kind is EntityKind.USE_CASE for item in graph.entities)
    assert any(item.kind is EntityKind.OPERATIONAL_SCENARIO for item in graph.entities)
    assert any(item.kind is EntityKind.ACTIVITY for item in graph.entities)
    assert any(
        event.get("kind") == "test.input_preparation"
        for event in repository.list_audit_events("p1")
    )


def test_stage_only_runtime_uses_legacy_input_adapter_without_extra_lens_call(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    model = SimpleNamespace()

    result = InputPreparationService(
        repository,
        SimpleNamespace(model=model),
    ).prepare("p1", requirement_text="系统应支持人工接管")
    graph = repository.load_graph("p1")

    assert result.mode == "legacy_requirement_input"
    assert any(item.kind is EntityKind.REQUIREMENT for item in graph.entities)
    assert not any(item.kind is EntityKind.USE_CASE for item in graph.entities)
