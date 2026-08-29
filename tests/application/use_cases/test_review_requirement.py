from __future__ import annotations

from types import SimpleNamespace

import pytest

from rflp_lite.application.requirements_workbench import review_item
from rflp_lite.application.use_cases.dependencies import ReviewRequirementDeps
from rflp_lite.application.use_cases.review_requirement import (
    ReviewRequirementCommand,
    ReviewRequirementUseCase,
)
from rflp_lite.domain.errors import ContractViolation


def _state() -> dict[str, object]:
    return {
        "revision": 3,
        "structured_requirements": [
            {"id": "req-1", "statement": "系统应可验证", "status": "candidate"}
        ],
        "rflp": {"elements": [{"id": "fn-1", "status": "accepted"}]},
        "mbse": {"semantic_model": {"model_hash": "old"}},
    }


def _use_case() -> ReviewRequirementUseCase:
    return ReviewRequirementUseCase(
        ReviewRequirementDeps(
            repository=SimpleNamespace(),
            review_policy=review_item,
            staleness_policy=lambda state, _ids: tuple(
                key for key in ("rflp", "mbse", "baseline") if state.get(key) is not None
            ),
        )
    )


def test_review_requirement_accepts_and_reports_stale_groups() -> None:
    result = _use_case().execute(
        _state(),
        ReviewRequirementCommand(
            group="structured_requirements",
            item_id="req-1",
            decision="accepted",
            expected_revision=3,
        ),
    )

    assert result.state["structured_requirements"][0]["status"] == "accepted"
    assert result.changed_ids == ("req-1",)
    assert result.stale_groups == ("rflp", "mbse")
    assert result.state["rflp"] is None
    assert result.state["mbse"] is None


def test_review_requirement_rejects_stale_revision() -> None:
    with pytest.raises(ContractViolation, match="版本已变化"):
        _use_case().execute(
            _state(),
            ReviewRequirementCommand(
                group="structured_requirements",
                item_id="req-1",
                decision="accepted",
                expected_revision=2,
            ),
        )
