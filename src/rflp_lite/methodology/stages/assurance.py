"""Assurance stage definition for behavior, hazards and V&V."""

from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult, global_gate
from rflp_lite.methodology.tasks import tasks_for_phase


def tasks():
    return tasks_for_phase(Phase.ASSURANCE)


def gate(graph) -> GateResult:
    return global_gate(graph)
