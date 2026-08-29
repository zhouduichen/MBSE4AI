from __future__ import annotations

import pytest

from rflp_lite.application.intelligence.dto import (
    ArchitectureRelationItem,
    RequirementItem,
    StakeholderItem,
    dto_to_dict,
    typed_item,
)
from rflp_lite.domain.errors import ContractViolation


def test_typed_dtos_normalize_collections_and_finite_confidence() -> None:
    stakeholder = typed_item(
        "stakeholders",
        {
            "id": "st-1",
            "name": "操作员",
            "category": "operator",
            "goals": ["安全运行"],
            "interactions": ["启动"],
            "source_region_ids": ["region-1"],
            "confidence": 0.8,
        },
    )
    requirement = RequirementItem.from_mapping(
        {
            "id": "req-1",
            "subject": "系统",
            "predicate": "应",
            "statement": "系统应可验证",
            "verification_method": "test",
            "source_region_ids": ["region-1"],
            "confidence": 1,
        }
    )

    assert isinstance(stakeholder, StakeholderItem)
    assert stakeholder.goals == ("安全运行",)
    assert dto_to_dict(requirement)["statement"] == "系统应可验证"


def test_relation_dto_has_deterministic_fallback_id_and_rejects_nonfinite() -> None:
    relation = ArchitectureRelationItem.from_mapping(
        {
            "source_id": "fn-1",
            "predicate": "allocatedTo",
            "target_id": "logic-1",
            "requirement_ids": [],
            "source_region_ids": [],
            "confidence": 0.5,
        }
    )
    assert relation.id.startswith("relation-")
    with pytest.raises(ContractViolation, match="有限数值"):
        RequirementItem.from_mapping(
            {
                "id": "req-1",
                "subject": "系统",
                "predicate": "应",
                "statement": "系统应可验证",
                "verification_method": "test",
                "source_region_ids": [],
                "confidence": float("nan"),
            }
        )
