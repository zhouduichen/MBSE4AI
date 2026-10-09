from rflp_lite.methodology.coverage_status import CoverageStatus, coverage_result
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.engine import MethodologyEngine


def test_empty_coverage_is_not_applicable():
    result = coverage_result(0, 0)

    assert result["covered_count"] == 0
    assert result["requirement_count"] == 0
    assert result["coverage"] is None
    assert result["status"] == CoverageStatus.NOT_APPLICABLE.value
    assert result["passed"] is False


def test_non_empty_coverage_has_pass_or_fail_and_ratio():
    assert coverage_result(2, 2)["status"] == CoverageStatus.PASS.value
    assert coverage_result(1, 2)["status"] == CoverageStatus.FAIL.value
    assert coverage_result(1, 2)["coverage"] == 0.5


def test_explicit_pass_override_can_fail_a_complete_scope():
    result = coverage_result(2, 2, passed=False)

    assert result["coverage"] == 1.0
    assert result["status"] == CoverageStatus.FAIL.value


def test_methodology_empty_scopes_are_not_reported_as_complete():
    metrics = MethodologyEngine().analyze(ModelGraph("empty")).metrics

    assert metrics["requirement_quality_coverage"] is None
    assert metrics["logical_state_model_coverage"] is None
    assert metrics["branch_execution_coverage"] is None
