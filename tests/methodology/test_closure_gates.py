from rflp_lite.domain.entities import EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.closure import (
    ClosureGate,
    evaluate_release_closure,
    evaluate_technical_closure,
)
from tests.methodology.test_strict_closure import _graph


def _codes(result):
    return {issue.code for issue in result.issues}


def test_validated_only_graph_passes_technical_but_fails_release():
    graph = _graph(
        requirement_status=EntityStatus.VALIDATED,
        downstream_status=EntityStatus.VALIDATED,
    )

    technical = evaluate_technical_closure(graph)
    release = evaluate_release_closure(graph)

    assert technical.passed is True
    assert technical.gate is ClosureGate.TECHNICAL
    assert release.passed is False
    assert release.gate is ClosureGate.RELEASE
    assert "fact_not_accepted" in _codes(release)


def test_release_closure_rejects_zero_accepted_requirements():
    result = evaluate_release_closure(ModelGraph("p1", ()))

    assert result.passed is False
    assert result.gate.value == "release"
    assert "empty_requirement_scope" in _codes(result)


def test_technical_closure_rejects_candidate_fact_even_with_a_trace():
    result = evaluate_technical_closure(
        _graph(
            requirement_status=EntityStatus.CANDIDATE,
            downstream_status=EntityStatus.VALIDATED,
        )
    )

    assert result.passed is False
    assert "requirement_not_validated" in _codes(result)
    assert "unresolved_candidate" in _codes(result)
