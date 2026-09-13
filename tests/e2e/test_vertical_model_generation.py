from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import Patch, UpdateEntity
from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
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
    assert result.methodology.metrics["operational_context_coverage"] == 1.0
    assert result.methodology.metrics["functional_requirement_coverage"] == 1.0
    assert result.methodology.metrics["functional_flow_coverage"] == 1.0
    assert result.methodology.metrics["functional_scenario_coverage"] == 1.0
    assert result.methodology.metrics["logical_allocation_coverage"] == 1.0
    assert result.methodology.metrics["verification_coverage"] == 1.0
    assert result.methodology.metrics["validation_coverage"] == 1.0
    assert result.methodology.metrics["structured_verification_coverage"] == 1.0
    assert result.methodology.metrics["structured_validation_coverage"] == 1.0
    assert result.methodology.metrics["verification_evidence_coverage"] == 0.0
    assert result.methodology.metrics["physical_feasibility"] == "needs_measurement"
    assert any(
        finding.code == "physical_measurement_required"
        for finding in result.methodology.findings
    )
    assert {EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK} <= {
        entity.kind for entity in graph.entities
    }
    assert graph.revision >= 6
    assert all("候选" not in entity.meta.name and "待确认" not in entity.meta.name for entity in graph.entities)

    exported = graph_to_sysml(graph)
    restored = sysml_to_graph(exported, "robot")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.model("robot").apply_patch(
        "robot",
        Patch.create(
            "robot",
            "review.edit",
            (UpdateEntity(function.id, {"payload": {"review_note": "人工可继续编辑"}}),),
            "验收编辑模型",
            graph.revision,
        ),
        graph.revision,
    )
    edited = services.model("robot").graph("robot")
    assert edited.entity_index[function.id].payload["review_note"] == "人工可继续编辑"
    assert "人工可继续编辑" in graph_to_sysml(edited)
