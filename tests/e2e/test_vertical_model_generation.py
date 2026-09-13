from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_natural_language_generation_is_editable_and_traceable(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园无人配送机器人")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应在校园内完成配送并支持人工接管"
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert result.traceability.complete_count == 1
    assert {EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK} <= {
        entity.kind for entity in graph.entities
    }
    assert graph.revision >= 6
