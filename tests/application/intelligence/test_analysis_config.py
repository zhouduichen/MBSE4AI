import pytest

from rflp_lite.application.intelligence.analysis_config import (
    DEFAULT_ANALYSIS_CONFIG,
    available_analysis_domain_packs,
    normalize_analysis_config,
)
from rflp_lite.application.intelligence.project_analysis import build_project_analysis_request
from rflp_lite.domain.errors import ContractViolation


def test_missing_config_is_domain_neutral_and_has_no_pack_guidance():
    config = normalize_analysis_config(None)

    assert config == DEFAULT_ANALYSIS_CONFIG
    assert config["enabled"] is False
    assert config["domain_pack_id"] is None
    assert config["domain_pack_version"] is None


def test_only_common_pack_can_be_enabled():
    packs = available_analysis_domain_packs()
    assert [item["id"] for item in packs] == ["common-v1"]

    config = normalize_analysis_config(
        {"enabled": True, "domain_pack_id": "common-v1", "domain_pack_version": 1}
    )

    assert config["enabled"] is True
    assert config["domain_pack_id"] == "common-v1"
    assert config["domain_pack_version"] == 1


@pytest.mark.parametrize("pack_id", ["fixed-wing", "urban-medical-aam-v1", "narrow-v1"])
def test_narrow_or_unknown_pack_cannot_become_project_analysis_default(pack_id: str):
    with pytest.raises(ContractViolation, match="常见领域包"):
        normalize_analysis_config(
            {"enabled": True, "domain_pack_id": pack_id, "domain_pack_version": 1}
        )


def test_request_keeps_default_analysis_domain_neutral():
    state = {
        "project_scope": {"workspace": "generic", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "设计一个新的系统"}],
        "claims": [],
        "stakeholders": [],
        "scenarios": [],
    }

    request = build_project_analysis_request(state)

    assert request.user_payload["analysis_config"]["enabled"] is False
    assert "domain_guidance" not in request.user_payload
    assert "urban-medical-aam-v1" not in str(request.user_payload)


def test_request_includes_common_guidance_only_when_explicitly_enabled():
    state = {
        "project_scope": {"workspace": "generic", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "设计一个新的系统"}],
        "claims": [],
        "stakeholders": [],
        "scenarios": [],
    }

    request = build_project_analysis_request(
        state,
        {
            "enabled": True,
            "domain_pack_id": "common-v1",
            "domain_pack_version": 1,
            "guidance": {"coverage_rules": ["every-stakeholder"]},
        },
    )

    assert request.user_payload["analysis_config"]["domain_pack_id"] == "common-v1"
    assert request.user_payload["domain_guidance"] == {
        "coverage_rules": ["every-stakeholder"]
    }
