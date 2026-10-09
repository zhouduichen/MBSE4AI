from dataclasses import FrozenInstanceError

import pytest

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import (
    ConstraintResult,
    DisciplineEvaluation,
    IndicatorEnvelope,
    LayoutCandidate,
    OptimizationRun,
    SchemeRecord,
    SimilarityMatch,
)


def test_concept_records_are_immutable_and_hashable_as_canonical_payloads():
    record = SchemeRecord(
        id="FW-S-1",
        object_type="layout",
        schema_version=1,
        domain_pack_id="fixed-wing",
        domain_pack_version=1,
        revision=1,
        status="imported",
        source="fixture.json:1",
        parameters=(("mass_kg", 120.0),),
        extensions=(("备注", "baseline"),),
        content_hash=canonical_hash(("FW-S-1", 120.0)),
    )
    assert canonical_hash(record) == canonical_hash(record)
    with pytest.raises(FrozenInstanceError):
        record.status = "changed"


def test_cross_task_records_keep_nested_traceable_contracts():
    match = SimilarityMatch("FW-S-1", 0.9, (("mass_kg", 0.02),), ())
    constraint = ConstraintResult("c-1", "FW-C-1", "aspect-ratio-min", "hard", 6.0, ">=", 4.0, 2.0, True, "ok")
    candidate = LayoutCandidate(
        "FW-C-1", "FW-E-1", "fixed-wing", 1, ("FW-S-1",), (match,),
        (("mass_kg", 120.0),), (("mass_kg", "envelope"),), (("span_m", 10.0),),
        "<svg></svg>", (constraint,), True, (), "feasible", "layout-generator-v1", 42, "input", "result",
    )
    evaluation = DisciplineEvaluation(
        "eval-1", candidate.id, "aerodynamics", "builtin.aerodynamics.v1", "1", "analytical",
        "input", "output", (("lift_to_drag", 12.0),), "succeeded", "development",
        (), (), "",
    )
    envelope = IndicatorEnvelope(
        "FW-E-1", "layout", 1, "fixed-wing", 1, 1, "draft", (), (("mass_kg", 120.0),), (), "input",
    )
    run = OptimizationRun(
        "run-1", envelope.id, "fixed-wing", 1, (candidate.id,), (evaluation.id,),
        (("iteration", 0),), (candidate.id,), 42, "budget", "input", "result", "completed", "development",
    )
    assert candidate.similarity_matches[0].scheme_id == match.scheme_id
    assert run.evaluation_ids == (evaluation.id,)

