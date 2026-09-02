from __future__ import annotations

from rflp_lite.application.requirement_clause_splitter import RequirementClauseSplitter


def test_split_preserves_behavior_and_normalizes_mixed_numeric_constraints() -> None:
    text = (
        "设计一型中程侦察无人机，最大起飞重量不超过 650 kg，"
        "任务载荷至少 150 kg，翼展 ≤ 16 m，巡航速度 >= 240 km/h，"
        "通信中断 30 秒后自动返航。"
    )

    clauses = RequirementClauseSplitter().split(text)

    assert len(clauses) == 1
    assert clauses[0].text == text.removesuffix("。")
    assert "通信中断 30 秒后自动返航" in clauses[0].text
    assert [metric.name for metric in clauses[0].normalized_metrics] == [
        "最大起飞重量",
        "任务载荷",
        "翼展",
        "巡航速度",
        "通信中断",
    ]
    metrics = {metric.name: metric for metric in clauses[0].normalized_metrics}
    assert metrics["最大起飞重量"].operator == "<="
    assert (metrics["最大起飞重量"].value, metrics["最大起飞重量"].unit) == (650.0, "kg")
    assert metrics["任务载荷"].operator == ">="
    assert metrics["翼展"].operator == "<="
    assert (metrics["巡航速度"].value, metrics["巡航速度"].unit) == (240.0, "km/h")
    assert metrics["通信中断"].unit == "s"


def test_split_uses_sentence_boundaries_without_breaking_decimal_values() -> None:
    text = "系统应满足截面模量等于 0.032 m3，许用应力等于 205000000 Pa。\n通信中断 30 秒后自动返航！"

    clauses = RequirementClauseSplitter().split(text)

    assert [item.text for item in clauses] == [
        "系统应满足截面模量等于 0.032 m3，许用应力等于 205000000 Pa",
        "通信中断 30 秒后自动返航",
    ]
    assert [metric.value for metric in clauses[0].normalized_metrics] == [0.032, 205000000.0]


def test_split_keeps_semicolons_and_connectors_inside_one_clause() -> None:
    text = "系统应支持自动巡检；并且任务载荷不少于 150 kg，以及航程不低于 100 km。"

    clauses = RequirementClauseSplitter().split(text)

    assert len(clauses) == 1
    assert clauses[0].text == text.removesuffix("。")
    assert [metric.name for metric in clauses[0].normalized_metrics] == ["任务载荷", "航程"]


def test_clause_ids_order_and_analyzed_requirements_are_stable() -> None:
    splitter = RequirementClauseSplitter()
    source = "翼展不超过 16 m，且任务载荷不少于 150 kg"

    first = splitter.analyze(source)
    second = splitter.analyze(source)

    assert first == second
    assert [item.ordinal for item in first.clauses] == [1]
    assert [item.id for item in first.clauses] == [item.id for item in second.clauses]
    assert len(first.requirements) == 1
    assert len(first.metrics) == 2
    assert first.requirements[0].source_region_id == first.clauses[0].source_region_id
