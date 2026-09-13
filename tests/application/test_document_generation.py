from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_document_regions_can_seed_the_vertical_generation_path(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园配送机器人")
    services.projects.ingest_uploaded(
        "robot",
        "requirements.txt",
        "系统应在校园内完成配送。系统应允许人工接管。".encode("utf-8"),
    )

    result = services.generation("robot").generate("robot")
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert any(item.kind is EntityKind.REQUIREMENT for item in graph.entities)
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    assert requirement.meta.source_ids
