from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.repair_context import RepairContext
from rflp_lite.methodology.repair_planner import plan
from rflp_lite.methodology.repair_strategies import LLMRepairStrategy
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse


class NoopRepairRuntime:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return TaskExecutionResponse(StepStatus.COMPLETED)


def test_llm_repair_strategy_uses_bounded_repair_prompt_and_noop_is_recoverable():
    entity = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"})
    context = RepairContext("p1", "run-1", "issue-1", "missing_function", "F-Gate", (entity.id,), 0, (entity,), (), ())
    task = plan(context)
    runtime = NoopRepairRuntime()
    strategy = LLMRepairStrategy(TaskExecutor(runtime))

    proposal = strategy.propose(context, task)

    assert proposal is not None
    assert proposal.patch is None
    assert proposal.strategy == "llm"
    assert runtime.requests[0].task_id == "repair.missing_function"
    assert "最小根因" in runtime.requests[0].prompt_text
