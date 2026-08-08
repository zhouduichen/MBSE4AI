from rflp_lite.application.requirement_semantics import extract_requirement_candidates


def test_customer_wording_extracts_entities_and_candidate_count():
    candidates = extract_requirement_candidates(
        ("支持导入作战纲要、技战术指标文档（Word/PDF）", "生成3~5套总体布局草图")
    )
    by_statement = {item.statement: item for item in candidates}
    support = by_statement["导入作战纲要、技战术指标文档（Word/PDF）"]
    assert support.subject == "系统"
    assert support.predicate == "支持"
    assert set(support.entities) >= {"作战纲要", "技战术指标文档", "Word", "PDF"}
    layouts = by_statement["3~5套总体布局草图"]
    assert ("candidate_count_min", "3") in layouts.constraints
    assert ("candidate_count_max", "5") in layouts.constraints

