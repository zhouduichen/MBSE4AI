import pytest

from rflp_lite.adapters.solvers import CpSatSolver, HeuristicSolver
from rflp_lite.application.compile import compile_claims
from rflp_lite.application.ingest import ingest_requirements
from rflp_lite.application.synthesize import synthesize_rflp
from rflp_lite.governance.profile import Profile


def rflp_elements():
    _, spans = ingest_requirements(__import__("pathlib").Path("examples/versioned-content-service/requirements.md"))
    elements, _ = synthesize_rflp(compile_claims(spans))
    return elements


@pytest.mark.parametrize("factory", [HeuristicSolver, CpSatSolver])
def test_solver_contract(factory):
    profile = Profile(candidate_limit=3)
    candidates = factory().solve(rflp_elements(), profile)
    assert 2 <= len(candidates) <= profile.candidate_limit
    assert [candidate.id for candidate in candidates] == sorted(candidate.id for candidate in candidates)
    assert all(candidate.score >= 0 for candidate in candidates)

