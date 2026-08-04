from rflp_lite.domain.models import Candidate
from rflp_lite.simulation.engine import simulate


def test_simulation_is_reproducible_and_ordered():
    candidate = Candidate("candidate-ports-adapters", "ports-adapters", ("core", "adapter"), 94)
    first = simulate(candidate, 42)
    second = simulate(candidate, 42)
    assert first == second
    assert [event.sequence for event in first.events] == [0, 1, 2, 3]
    assert first.passed

