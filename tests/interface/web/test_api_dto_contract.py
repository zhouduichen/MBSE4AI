from __future__ import annotations

import pytest

from rflp_lite.domain.errors import ValidationError
from rflp_lite.interface.web.dto import RequirementReviewRequest, to_application_payload


def test_interface_dto_validates_and_converts_to_plain_command_payload() -> None:
    request = RequirementReviewRequest(
        group="claims", item_id="req-1", status="accepted", expected_revision=3
    )

    assert to_application_payload(request)["expected_revision"] == 3
    assert to_application_payload(request)["item_id"] == "req-1"


def test_typed_error_mapper_exposes_stable_code() -> None:
    from rflp_lite.interface.web.error_mapper import map_error

    status, payload = map_error(ValidationError("invalid"))
    assert status == 422
    assert payload["error_code"] == "validation_error"
