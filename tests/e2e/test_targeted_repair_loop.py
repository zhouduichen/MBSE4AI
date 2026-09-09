from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.methodology.contracts import RunStatus
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository


class OfflineNoopRuntime:
    def execute(self, request):
        from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
        return TaskExecutionResponse(StepStatus.COMPLETED)


def test_targeted_repair_prefers_llm_then_uses_rule_fallback(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED)
    repository.append_patch("p1", Patch.create("p1", "seed", (AddEntity(requirement),), "seed", 0), 0)
    repository.save_issue("p1", {"id": "issue-1", "code": "missing_function", "entity_ids": [requirement.id]})
    runner = WorkflowRunner(repository, repository, OfflineNoopRuntime())

    summary = runner.repair("p1", "issue-1")
    graph = repository.load_graph("p1")
    repaired = [entity for entity in graph.entities if entity.kind is EntityKind.FUNCTION]

    assert summary.status is RunStatus.COMPLETED
    assert repaired
    assert repaired[0].meta.producer.value == "rule"
    assert "strategy=rule_fallback" in summary.diagnostics
