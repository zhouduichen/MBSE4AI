from rflp_lite.application.requirement_clause_splitter import RequirementClauseSplitter


DEMO_TEXT = (
    "设计一型中程侦察无人机，最大起飞重量不超过500kg，"
    "航程不低于800km，翼展不超过12m，任务载荷不低于50kg，"
    "通信中断30秒后自动返航"
)


def test_splitter_extracts_five_numeric_constraints_and_behavior():
    analysis = RequirementClauseSplitter().analyze(DEMO_TEXT)
    metrics = {
        metric.name: (metric.operator, metric.value, metric.unit)
        for clause in analysis.clauses
        for metric in clause.normalized_metrics
    }
    assert metrics["最大起飞重量"] == ("<=", 500.0, "kg")
    assert metrics["航程"] == (">=", 800.0, "km")
    assert metrics["翼展"] == ("<=", 12.0, "m")
    assert metrics["任务载荷"] == (">=", 50.0, "kg")
    assert metrics["通信中断"] == ("==", 30.0, "s")
    assert any("自动返航" in clause.text for clause in analysis.clauses)


def test_splitter_is_stable_for_repeated_input():
    splitter = RequirementClauseSplitter()
    assert splitter.analyze(DEMO_TEXT) == splitter.analyze(DEMO_TEXT)


def test_operator_aliases_are_normalized():
    result = RequirementClauseSplitter().analyze(
        "质量不得大于2kg，航程至少10km，速度不高于100km/h"
    )
    assert [
        (metric.operator, metric.value, metric.unit)
        for clause in result.clauses
        for metric in clause.normalized_metrics
    ] == [
        ("<=", 2.0, "kg"),
        (">=", 10.0, "km"),
        ("<=", 100.0, "km/h"),
    ]
