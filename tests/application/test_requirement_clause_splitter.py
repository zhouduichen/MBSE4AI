from __future__ import annotations

from rflp_lite.application.requirement_clause_splitter import RequirementClauseSplitter


def test_split_preserves_behavior_and_normalizes_mixed_numeric_constraints() -> None:
    text = (
        "设计一型中程侦察无人机，最大起飞重量不超过 650 kg，"
        "任务载荷至少 150 kg，翼展 ≤ 16 m，巡航速度 >= 240 km/h，"
        "通信中断 30 秒后自动返航。"
    )

    clauses = RequirementClauseSplitter().split(text)

    assert [item.kind for item in clauses] == [
        "mission",
        "metric",
        "metric",
        "metric",
        "metric",
        "behavior",
    ]
    metrics = {
        item.normalized_metrics[0].name: item.normalized_metrics[0]
        for item in clauses
        if item.normalized_metrics and item.kind == "metric"
    }
    assert metrics["最大起飞重量"].operator == "<="
    assert (metrics["最大起飞重量"].value, metrics["最大起飞重量"].unit) == (650.0, "kg")
    assert metrics["任务载荷"].operator == ">="
    assert metrics["翼展"].operator == "<="
    assert (metrics["巡航速度"].value, metrics["巡航速度"].unit) == (240.0, "km/h")
    assert "通信中断 30 秒后自动返航" in clauses[-1].text
    assert clauses[-1].normalized_metrics[0].unit == "s"


def test_clause_ids_order_and_analyzed_requirements_are_stable() -> None:
    splitter = RequirementClauseSplitter()
    source = "翼展不超过 16 m，且任务载荷不少于 150 kg"

    first = splitter.analyze(source)
    second = splitter.analyze(source)

    assert first == second
    assert [item.ordinal for item in first.clauses] == [1, 2]
    assert [item.id for item in first.clauses] == [item.id for item in second.clauses]
    assert len(first.requirements) == 2
    assert all(item.source_region_id == first.clauses[index].source_region_id for index, item in enumerate(first.requirements))
