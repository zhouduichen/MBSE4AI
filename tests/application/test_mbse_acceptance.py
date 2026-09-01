from rflp_lite.application.mbse_acceptance import evaluate_mbse_acceptance
from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact


def _reviewed_state():
    return accept_traceable(analyze_artifact("requirements.txt", "支持导入 PDF。".encode()))


def test_mbse_acceptance_requires_one_canonical_flow_across_views():
    state = generate_mbse_revision(_reviewed_state())
    metrics = evaluate_mbse_acceptance(state)
    assert metrics["requirement_coverage"] == 1.0
    assert metrics["cross_view_consistency"] == 1.0
    assert metrics["trace_complete"] == 1.0
    assert metrics["projection_complete"] is True


def test_mbse_edit_cas_and_targeted_stale_are_verified_without_persisting():
    state = generate_mbse_revision(_reviewed_state())
    metrics = evaluate_mbse_acceptance(state)
    assert metrics["edit_cas_verified"] is True
    assert metrics["edited_target_id"]
    assert metrics["unrelated_stale_count"] == 0


def test_different_flow_hash_is_not_consistent():
    state = generate_mbse_revision(_reviewed_state())
    state["mbse"]["messages"][0]["canonical_flow_hash"] = "wrong"
    assert evaluate_mbse_acceptance(state)["cross_view_consistency"] < 1.0
