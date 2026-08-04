from __future__ import annotations

from graphlib import TopologicalSorter

from rflp_lite.domain.models import Delta, TaskContract


def build_task_contracts(delta: Delta) -> tuple[TaskContract, ...]:
    tasks: list[TaskContract] = []
    previous: str | None = None
    for index, item in enumerate(delta.items[:3], 1):
        task_id = f"task-{index}-{item.target_id.replace('_', '-')}"
        dependencies = (previous,) if previous else ()
        tasks.append(
            TaskContract(
                id=task_id,
                target_ids=(item.target_id,),
                read_set=("baseline.json", "evidence.json"),
                write_set=(f"implementation/{item.target_id}",),
                invariants=("approved baseline hash must not change",),
                acceptance=(f"resolve {item.kind} delta {item.id}", "tests must pass"),
                depends_on=dependencies,
            )
        )
        previous = task_id
    graph = {task.id: set(task.depends_on) for task in tasks}
    order = tuple(TopologicalSorter(graph).static_order())
    by_id = {task.id: task for task in tasks}
    return tuple(by_id[task_id] for task_id in order)

