from rflp_lite.application.projections.assurance import build_assurance_view
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def test_assurance_projection_does_not_fabricate_verification_or_hazard_facts():
    requirement = make_entity(EntityKind.REQUIREMENT, "R", status=EntityStatus.ACCEPTED)
    hazard = make_entity(EntityKind.HAZARD, "Overheating")
    graph = ModelGraph("p1", (requirement, hazard), (Relation("cause", hazard.id, RelationPredicate.CAUSES, requirement.id),))
    view = build_assurance_view(graph)
    assert view["verification_validation"][0]["status"] == "MISSING_VERIFICATION"
    assert view["hazards"][0]["name"] == "Overheating"
    assert view["hazards"][0]["mitigations"] == []


def test_assurance_projection_exposes_executable_plan_and_separates_evidence():
    requirement = make_entity(EntityKind.REQUIREMENT, "R", status=EntityStatus.ACCEPTED)
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证 R",
        {
            "method": "test",
            "verification_objective": "证明 R 满足",
            "precondition": "设备已部署",
            "test_condition": "额定负载和边界工况",
            "input": "任务数据",
            "stimulus": "提交任务",
            "procedure": "执行任务并记录结果",
            "expected_result": "系统完成任务",
            "pass_criteria": "结果满足 R",
            "evidence_ids": ["source-evidence"],
            "execution_evidence_ids": [],
        },
        status=EntityStatus.VALIDATED,
    )
    graph = ModelGraph(
        "p1",
        (requirement, verification),
        (Relation("verify", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),),
    )

    row = build_assurance_view(graph)["verification_validation"][0]

    assert row["test_condition"] == "额定负载和边界工况"
    assert row["stimulus"] == "提交任务"
    assert row["execution_evidence_ids"] == []
    assert row["plan_status"] == "PASS"
