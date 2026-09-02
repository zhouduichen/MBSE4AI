from __future__ import annotations

from types import SimpleNamespace

from rflp_lite.application.multidisciplinary_optimization import (
    pareto_front,
    rank_evaluated_candidates,
    run_optimization,
)
from rflp_lite.domain.concept_design import DisciplineEvaluation, LayoutCandidate


def _candidate(identifier: str) -> LayoutCandidate:
    return LayoutCandidate(
        id=identifier,
        envelope_id="E1",
        domain_pack_id="demo",
        domain_pack_version=1,
        reference_ids=(),
        similarity_matches=(),
        parameters=(("mass_kg", 100.0),),
        parameter_sources=(),
        geometry=(),
        svg="<svg />",
        constraints=(),
        feasible=True,
        infeasible_reasons=(),
        status="feasible",
        generator_version="test",
        seed=42,
        input_hash=identifier,
        result_hash=f"hash-{identifier}",
    )


def _evaluation(candidate_id: str, value: float) -> DisciplineEvaluation:
    return DisciplineEvaluation(
        id=f"{candidate_id}:adapter",
        candidate_id=candidate_id,
        discipline="quality",
        adapter_id="adapter",
        adapter_version="1",
        source_kind="analytical",
        input_hash=candidate_id,
        output_hash=f"output-{candidate_id}",
        metrics=(("score", value),),
        status="succeeded",
        evidence_status="development",
        validity=(),
        diagnostics=(),
        log_ref="",
    )


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


def test_optimization_records_parents_and_adds_second_generation_candidates():
    initial = _candidate("C1")
    generated_candidates = (_candidate("C2"), _candidate("C3"))
    parent_batches: list[tuple[str, ...]] = []

    def generate(_pack, parents, _seed):
        parent_batches.append(tuple(item.id for item in parents))
        return generated_candidates

    def evaluate(candidates, _pack, _profile):
        return SimpleNamespace(
            evaluations=tuple(
                _evaluation(item.id, float(index + 2))
                for index, item in enumerate(candidates)
            )
        )

    result = run_optimization(
        {
            "id": "demo",
            "version": 1,
            "disciplines": [{"id": "quality"}],
            "objectives": [{"discipline": "quality", "metric": "score", "direction": "minimize"}],
        },
        {"id": "development", "version": 1, "approvals": {}},
        (initial,),
        (_evaluation("C1", 10.0),),
        generate,
        evaluate,
        iterations=1,
        evaluation_budget=3,
        base_seed=42,
    )

    assert parent_batches == [("C1",)]
    assert result.run.candidate_ids == ("C1", "C2", "C3")
    assert result.run.iteration_records[0][1]["generation_index"] == 0
    assert result.run.iteration_records[1][1]["parent_ids"] == ("C1",)
    assert result.run.iteration_records[1][1]["candidate_ids"] == ("C2", "C3")
    assert result.run.iteration_records[1][1]["generation_index"] == 1
