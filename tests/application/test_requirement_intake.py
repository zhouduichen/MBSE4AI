from rflp_lite.application.requirement_intake import (
    extract_requirement_constraints,
    split_requirement_statements,
)


def test_extracts_compound_chinese_constraints_and_normalizes_units():
    result = extract_requirement_constraints(
        "系统功耗不超过 50 W，质量不大于 2 kg，续航不少于 10 h"
    )

    assert result["constraints"] == {
        "max_power_w": 50.0,
        "max_mass_kg": 2.0,
        "min_endurance_h": 10.0,
    }
    assert [item["field"] for item in result["constraint_provenance"]] == [
        "power_w", "mass_kg", "endurance_h",
    ]


def test_extracts_english_comparators_and_converts_units():
    result = extract_requirement_constraints(
        "Power <= 0.5 kW; latency must be at most 2 s; bandwidth >= 1 Gbps"
    )

    assert result["constraints"] == {
        "max_power_w": 500.0,
        "max_latency_ms": 2000.0,
        "min_bandwidth_mbps": 1000.0,
    }


def test_keeps_strictest_duplicate_bound_and_preserves_both_directions():
    result = extract_requirement_constraints(
        "功耗不超过 80 W，功耗不超过 50 W，功耗不少于 10 W"
    )

    assert result["constraints"] == {
        "max_power_w": 50.0,
        "min_power_w": 10.0,
    }
    assert len(result["constraint_provenance"]) == 2


def test_does_not_infer_from_bare_numbers_or_version_text():
    assert extract_requirement_constraints("系统版本 2.0，支持 3 个用户") == {}
    assert extract_requirement_constraints("系统续航 10 小时") == {}


def test_splitter_preserves_order_and_removes_list_prefixes():
    assert split_requirement_statements(
        "1. 系统应自主配送；\n- 系统应支持人工接管。\n系统应在 12.5 h 内完成。"
    ) == (
        "系统应自主配送",
        "系统应支持人工接管",
        "系统应在 12.5 h 内完成",
    )


def test_splitter_handles_english_sentence_boundaries_without_splitting_versions():
    assert split_requirement_statements(
        "The system shall stop safely. The system shall log v2.0."
    ) == (
        "The system shall stop safely",
        "The system shall log v2.0",
    )


def test_splitter_ignores_blank_entries():
    assert split_requirement_statements("；\n  \n系统应可用！") == ("系统应可用",)
