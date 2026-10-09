from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.domain.model import ModelGraph


def test_empty_traceability_view_is_not_applicable():
    view = build_traceability_view(ModelGraph("p1", (), ()))

    assert view["metrics"]["status"] == "not_applicable"
    assert view["metrics"]["coverage"] is None
    assert view["metrics"]["covered_count"] == 0
    assert view["metrics"]["requirement_count"] == 0
    assert view["metrics"]["average_coverage_percent"] is None
