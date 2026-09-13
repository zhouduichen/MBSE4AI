from rflp_lite.application.requirement_intake import split_requirement_statements


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
