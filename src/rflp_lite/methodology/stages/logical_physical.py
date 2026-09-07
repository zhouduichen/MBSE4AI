"""CESAM white-box logical and physical stage definition."""

from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult, rflp_gate
from rflp_lite.methodology.tasks import tasks_for_phase


def tasks():
    return tasks_for_phase(Phase.LOGICAL_PHYSICAL)


def gate(graph) -> GateResult:
    return rflp_gate(graph)
