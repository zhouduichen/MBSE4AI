from __future__ import annotations

from rflp_lite.application.multidisciplinary_optimization import pareto_front, rank_evaluated_candidates


def test_pareto_front_keeps_non_dominated_candidates():
    vectors = {"a": (12.0, 100.0), "b": (10.0, 90.0), "c": (11.0, 120.0)}
    objectives = (("maximize", "lift_to_drag"), ("minimize", "mass"))
    assert pareto_front(vectors, objectives) == ("a", "b")


def test_partial_candidate_is_not_ranked():
    class Candidate:
        id = "candidate-partial"

    candidate = Candidate()
    evaluations = ()
    objectives = ({"discipline": "aerodynamics", "metric": "lift_to_drag", "direction": "maximize"},)
    assert rank_evaluated_candidates((candidate,), evaluations, objectives) == ()
