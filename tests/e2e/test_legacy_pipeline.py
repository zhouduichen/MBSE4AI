from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.methodology.contracts import RunStatus


def test_pipeline_from_natural_language_creates_operational_and_functional_layers(
    tmp_path: Path,
):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统应支持自主配送并允许人工接管"
    )

    summary = services.analysis("robot").run("robot", force_new=True)

    graph = services.model("robot").graph("robot")
    kinds = {item.kind for item in graph.entities}
    assert {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
    } <= kinds
    assert summary.status is RunStatus.COMPLETED
    assert len(summary.completed_tasks) == 23
