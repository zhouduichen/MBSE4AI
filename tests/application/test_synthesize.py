from rflp_lite.application.synthesize import synthesize_rflp
from rflp_lite.domain.models import Claim


def _claim(identifier: str, text: str) -> Claim:
    return Claim(identifier, "span-1", "系统", "应", text, 0.9, "accepted")


def test_llm_architecture_expands_rflp_and_keeps_requirement_traceability():
    claims = (_claim("r1", "限制压力"), _claim("r2", "记录使用数据"))
    architecture = {
        "functions": [
            {"id": "f-pressure", "name": "压力控制", "requirement_ids": ["r1"]},
            {"id": "f-record", "name": "使用记录", "requirement_ids": ["r2"]},
        ],
        "logical_components": [
            {"id": "l-controller", "name": "控制逻辑", "requirement_ids": ["r1", "r2"]}
        ],
        "physical_components": [
            {"id": "p-sensor", "name": "压力传感器", "requirement_ids": ["r1"]},
            {"id": "p-memory", "name": "存储模块", "requirement_ids": ["r2"]},
        ],
        "interfaces": [
            {"id": "i-data", "name": "传感器数据接口", "source_id": "p-sensor", "target_id": "l-controller"}
        ],
        "relations": [],
    }

    elements, relations = synthesize_rflp(claims, architecture)

    assert {item.name for item in elements if item.layer == "F"} == {"压力控制", "使用记录"}
    assert {item.predicate for item in relations} >= {"satisfiedBy", "allocatedTo", "realizedBy", "exchanges"}
    ids = {item.id for item in elements}
    assert all(item.source_id in ids and item.target_id in ids for item in relations)


def test_missing_architecture_uses_explicit_needs_analysis_placeholders():
    elements, relations = synthesize_rflp((_claim("r1", "限制压力"),), {})

    assert {item.layer for item in elements} == {"R", "F", "L", "P"}
    assert any(item.status == "needs-analysis" for item in elements)
    assert all(item.name != "Python Service" for item in elements)
    assert {item.predicate for item in relations} == {"satisfiedBy", "allocatedTo", "realizedBy"}
