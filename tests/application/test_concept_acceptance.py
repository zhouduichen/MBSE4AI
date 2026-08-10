from pathlib import Path

from rflp_lite.application.concept_acceptance import run_concept_acceptance


ROOT = Path("src/rflp_lite/resources/examples/concept-design")
PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def test_concept_acceptance_proves_21_and_22():
    report = run_concept_acceptance(
        PACK,
        ROOT / "fixed-wing-schemes.json",
        ROOT / "fixed-wing-envelope.json",
        ROOT / "development-evaluator-profile.json",
    )
    assert report["status"] == "passed"
    assert report["formal_status"] == "development_only"
    assert report["checks"]["2.1.candidate_count"] is True
    assert report["checks"]["2.1.hard_constraints"] is True
    assert report["checks"]["2.1.reproducible"] is True
    assert report["checks"]["2.2.three_disciplines"] is True
    assert report["checks"]["2.2.failure_isolation"] is True
    assert report["checks"]["2.2.optimization_trace"] is True
    assert report["checks"]["2.2.approval_gate"] is True
