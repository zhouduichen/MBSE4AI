"""CESAM black-box operational stage definition."""

from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult, operational_gate
from rflp_lite.methodology.tasks import tasks_for_phase


def tasks():
    return tasks_for_phase(Phase.OPERATIONAL)


def gate(graph) -> GateResult:
    return operational_gate(graph)
