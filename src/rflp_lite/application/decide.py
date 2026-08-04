from __future__ import annotations

from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Candidate, Decision, SimulationRun


def select_candidate(
    candidates: tuple[Candidate, ...], simulations: tuple[SimulationRun, ...]
) -> Decision:
    passing = {simulation.candidate_id for simulation in simulations if simulation.passed}
    eligible = [candidate for candidate in candidates if candidate.id in passing]
    if not eligible:
        raise InvariantViolation("no candidate passed simulation")
    selected = sorted(eligible, key=lambda item: (-item.score, item.id))[0]
    return Decision(
        id=f"decision-{selected.id.removeprefix('candidate-')}",
        candidate_id=selected.id,
        score=selected.score,
        rationale=("highest passing normalized score", "stable id tie-break"),
    )

