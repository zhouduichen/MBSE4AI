from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository


class NoopRuntime:
    def execute(self, request):
        from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
        return TaskExecutionResponse(StepStatus.COMPLETED)


def test_semantic_failure_blocks_later_phases_and_closure(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    entities = (
        make_entity(EntityKind.STAKEHOLDER, "用户"),
        make_entity(EntityKind.LIFECYCLE_STAGE, "运行"),
        make_entity(EntityKind.SCENARIO_HYPOTHESIS, "正常配送"),
        make_entity(EntityKind.USE_CASE, "完成配送"),
        make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED),
        make_entity(EntityKind.FUNCTION, "支持配送"),
        make_entity(EntityKind.LOGICAL_COMPONENT, "配送逻辑"),
    )
    requirement, function, logical = entities[-3:]
    repository.append_patch(
        "p1",
        Patch.create("p1", "seed", tuple([AddEntity(entity) for entity in entities] + [Relate(requirement.id, RelationPredicate.SATISFIED_BY, logical.id)]), "seed", 0),
        0,
    )
    summary = WorkflowRunner(repository, repository, NoopRuntime()).run("p1")

    assert summary.status.value == "degraded"
    assert "completion_minimum_entities" in summary.diagnostics
    assert summary.closure is not None
    assert summary.closure["status"] == "blocked"
