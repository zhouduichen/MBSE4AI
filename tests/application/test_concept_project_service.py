from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


ROOT = Path("src/rflp_lite/resources/examples/concept-design")


def test_project_concept_service_generates_and_applies_layout_candidate(tmp_path):
    services = build_v2_services(tmp_path)
    services.projects.create("mission")
    envelope = json.loads((ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))

    result = services.concept_design("mission").run(envelope, optimize=False)

    assert 3 <= len(result.candidates) <= 5
    assert len(result.evaluations) == len(result.candidates) * 3
    assert result.evaluation_summary["candidate_count"] == len(result.candidates)
    assert result.evaluation_summary["evaluation_count"] == len(result.evaluations)
    assert result.evaluation_summary["complete_candidate_count"] == len(result.candidates)
    assert result.evaluation_summary["optimization_evidence_status"] == "development"
    assert result.evaluation_summary["iterations"]
    applied = services.concept_design("mission").apply_candidate(result.candidates[0].id, result.id)
    assert applied["entity"]["kind"] == EntityKind.PHYSICAL_BLOCK.value
    repeated = services.concept_design("mission").apply_candidate(result.candidates[0].id, result.id)
    assert repeated["idempotent"] is True

    graph = services.repository("mission").load_graph("mission")
    assert any(item.kind is EntityKind.PHYSICAL_BLOCK for item in graph.entities)
    assert services.concept_design("mission").latest().id == result.id


def test_requirements_feed_indicator_envelope_and_layout_candidates(tmp_path):
    services = build_v2_services(tmp_path, runtime=VerticalRuleRuntime())
    services.projects.create("handoff", "固定翼总体设计")
    services.generation("handoff").generate(
        "handoff",
        requirement_text=(
            "最大起飞重量为 560 kg；任务载荷为 180 kg；机翼面积为 24 m2；"
            "翼展为 13 m；机身长度为 9 m；巡航速度为 66 m/s；"
            "截面模量为 0.032 m3；许用应力为 205000000 Pa；重心位置为 2.7 m"
        ),
    )

    suggestion = services.concept_design("handoff").suggest_input()

    assert suggestion["status"] == "ready"
    assert suggestion["missing_parameters"] == []
    assert suggestion["envelope"]["parameters"] == {
        "allowable_stress_pa": 205000000.0,
        "cg_x_m": 2.7,
        "cruise_speed_mps": 66.0,
        "fuselage_length_m": 9.0,
        "mass_kg": 560.0,
        "payload_kg": 180.0,
        "section_modulus_m3": 0.032,
        "span_m": 13.0,
        "wing_area_m2": 24.0,
    }
    assert len(suggestion["evidence"]) == 9

    concept = services.concept_design("handoff").run(
        suggestion["envelope"],
        optimize=False,
    )

    assert 3 <= len(concept.candidates) <= 5
    assert len(concept.evaluations) == len(concept.candidates) * 3
    assert concept.envelope.source_requirement_ids == tuple(
        suggestion["source_requirement_ids"]
    )


def test_requirements_preserve_minimum_and_maximum_comparator_evidence(tmp_path):
    services = build_v2_services(tmp_path, runtime=VerticalRuleRuntime())
    services.projects.create("bounds", "固定翼总体设计")
    services.generation("bounds").generate(
        "bounds",
        requirement_text="最大起飞重量不超过 650 kg；任务载荷不少于 150 kg",
    )

    suggestion = services.concept_design("bounds").suggest_input()

    assert suggestion["envelope"]["bounds"] == {
        "mass_kg": {"maximum": 650.0},
        "payload_kg": {"minimum": 150.0},
    }
    assert {
        (item["parameter"], item["operator"], item["value"])
        for item in suggestion["evidence"]
    } == {
        ("mass_kg", "max", 650.0),
        ("payload_kg", "min", 150.0),
    }
