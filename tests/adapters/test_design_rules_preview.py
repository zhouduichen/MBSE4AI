from __future__ import annotations

from rflp_lite.adapters.design_rules_preview import PreviewDesignRuleAdapter


def _shell_model() -> dict:
    return {
        "parts": [{
            "id": "housing",
            "material": "铝合金",
            "bbox_mm": [120, 80, 60],
            "features": [{
                "id": "shell",
                "kind": "create_shell",
                "parameters": {"wall_thickness_mm": 1.5},
            }],
        }],
    }


def test_rule_set_changes_threshold_and_is_recorded_in_evidence():
    adapter = PreviewDesignRuleAdapter()

    generic = adapter.review(_shell_model(), {"rule_set": "generic_preview"})
    cnc = adapter.review(_shell_model(), {"rule_set": "cnc_machined"})

    assert not any(item.rule_id == "dfm.wall_thickness" for item in generic.findings)
    wall = next(item for item in cnc.findings if item.rule_id == "dfm.wall_thickness")
    assert dict(wall.evidence)["rule_set"] == "cnc_machined"
    assert dict(wall.evidence)["minimum_mm"] == 2.0
    assert cnc.artifacts["rule_set"] == "cnc_machined"


def test_unknown_rule_set_and_missing_assembly_interface_are_review_findings():
    result = PreviewDesignRuleAdapter().review(
        _shell_model(),
        {
            "rule_set": "customer_unknown_v9",
            "assembly_interfaces": [{
                "part_id": "housing",
                "feature_id": "mounting-hole-1",
                "interface": "mounting",
                "required": True,
            }],
        },
    )

    assert {item.rule_id for item in result.findings} >= {
        "ruleset.unknown", "dfa.assembly_interface",
    }
    assert result.artifacts["finding_summary"]["by_severity"]["high"] >= 2
    assert result.artifacts["evidence_hash"]
    assert result.artifacts["risk_highlight_svg"].startswith("<svg")
