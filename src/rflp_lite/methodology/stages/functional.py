"""CESAM grey-box functional stage definition."""

from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult, functional_gate
from rflp_lite.methodology.tasks import tasks_for_phase


def tasks():
    return tasks_for_phase(Phase.FUNCTIONAL)


def gate(graph) -> GateResult:
    return functional_gate(graph)
